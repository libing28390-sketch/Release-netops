"""Append-only Document/Document Version boundary for ING-013.

The service owns the first durable V2 version seam while V1 ``ai_document``
remains readable and writable through its existing adapter.  A canonical URL
identifies one stable document inside a tenant; each new server-owned source
content hash appends one immutable document version.  Repeated hashes replay
the existing version and never overwrite facts.
"""

from __future__ import annotations

import hashlib
import json
import difflib
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import database as _database
from core.rbac import authorize_resource
from database import get_db_connection
from services.audit_service import log_audit_event


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DOCUMENT_STATUSES = {"draft", "active", "disabled", "archived", "deleted", "quarantined", "purged"}
_VERSION_STATUSES = _DOCUMENT_STATUSES
_TRUST_LEVELS = {"official", "reviewed", "internal", "untrusted"}
_SAFE_METADATA_KEYS = {
    "source_kind",
    "vendor",
    "product_family",
    "product_series",
    "product_model",
    "document_kind",
    "title",
    "language",
    "version_scope",
    "metadata_parse_status",
    "verification_level",
}


class DocumentVersionError(ValueError):
    """Stable, user-safe document version error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system")[:256]


def _tenant(user: dict[str, Any]) -> str:
    tenant_id = str(user.get("tenant_id") or "tenant-default").strip()
    if not tenant_id or len(tenant_id) > 256 or _CONTROL_RE.search(tenant_id):
        raise DocumentVersionError("DOCUMENT_TENANT_INVALID", "tenant_id is invalid")
    return tenant_id


def _safe_text(value: Any, *, field: str, maximum: int = 512, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise DocumentVersionError("DOCUMENT_FIELD_REQUIRED", f"{field} is required")
    if len(text) > maximum or _CONTROL_RE.search(text):
        raise DocumentVersionError("DOCUMENT_FIELD_INVALID", f"{field} is invalid")
    return text


def _canonical_url(value: Any) -> str:
    raw = _safe_text(value, field="canonical_url", maximum=4096, required=True)
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise DocumentVersionError("DOCUMENT_URL_INVALID", "canonical_url is invalid") from exc
    if parsed.scheme.lower() != "https" or not host or port not in (None, 443):
        raise DocumentVersionError("DOCUMENT_URL_INVALID", "canonical_url must be an HTTPS URL")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise DocumentVersionError("DOCUMENT_URL_INVALID", "canonical_url contains forbidden identity material")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise DocumentVersionError("DOCUMENT_URL_INVALID", "canonical_url host is invalid") from exc
    path = parsed.path or "/"
    if "\\" in path or _CONTROL_RE.search(path):
        raise DocumentVersionError("DOCUMENT_URL_INVALID", "canonical_url path is invalid")
    segments: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    normalized_path = "/" + "/".join(segments)
    if path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    return urlunsplit(("https", host, normalized_path or "/", "", ""))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


try:
    import sqlite3
    from psycopg2.extras import Json as _PgJson
    sqlite3.register_adapter(_PgJson, lambda j: _json_dumps(getattr(j, "adapted", j)))
except Exception:
    pass


def _json_db_value(value: dict[str, Any]) -> Any:
    if _database._USE_PG:
        try:
            from psycopg2.extras import Json

            return Json(value, dumps=lambda item: _json_dumps(item))
        except ImportError:
            pass
    return _json_dumps(value)


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise DocumentVersionError("DOCUMENT_METADATA_INVALID", "metadata must be an object")
    result: dict[str, Any] = {}
    for key in sorted(_SAFE_METADATA_KEYS):
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, str):
            result[key] = _safe_text(value, field=f"metadata.{key}", maximum=2_000)
        elif isinstance(value, (int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, dict) and key == "version_scope":
            scoped: dict[str, str] = {}
            for scope_key in ("primary", "compatibility"):
                if scope_key in value:
                    scoped[scope_key] = _safe_text(value[scope_key], field=f"metadata.version_scope.{scope_key}", maximum=128)
            result[key] = scoped
        else:
            raise DocumentVersionError("DOCUMENT_METADATA_INVALID", f"metadata.{key} is invalid")
    encoded = _json_dumps(result).encode("utf-8")
    if len(encoded) > 256 * 1024:
        raise DocumentVersionError("DOCUMENT_METADATA_TOO_LARGE", "metadata exceeds the configured limit")
    return result


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _decode(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["metadata"] = _json_load(result.pop("metadata_json", None), {})
    result["acl"] = _json_load(result.pop("acl_json", None), {})
    return result


def _decode_observation(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["metadata"] = _json_load(result.pop("metadata_json", None), {})
    return result


def _merge_compatible(
    candidate_document: dict[str, Any],
    candidate_version: dict[str, Any],
    *,
    trust_level: str,
    parser_name: str,
    parser_version: str,
    document_kind: str,
) -> bool:
    """Only merge bytes when retrieval trust and parsing contracts agree."""
    return (
        str(candidate_document.get("status") or "") not in {"deleted", "purged", "quarantined", "disabled"}
        and str(candidate_version.get("status") or "") not in {"deleted", "purged", "quarantined", "disabled"}
        and str(candidate_document.get("trust_level") or "") == trust_level
        and str(candidate_version.get("trust_level") or "") == trust_level
        and str(candidate_version.get("parser_name") or "") == parser_name
        and str(candidate_version.get("parser_version") or "") == parser_version
        and str(candidate_document.get("document_kind") or "") == document_kind
    )


def _link_source_observation(
    cursor,
    *,
    tenant_id: str,
    document: dict[str, Any],
    version: dict[str, Any],
    source: dict[str, Any],
    source_version: dict[str, Any],
    canonical_url: str,
    content_hash: str,
    metadata: dict[str, Any],
    actor: str,
    now: str,
) -> dict[str, Any]:
    """Create or count one immutable source observation without raw bytes."""
    source_version_id = str(source_version.get("id") or "")
    existing = cursor.execute(
        "SELECT * FROM kb_document_source WHERE tenant_id = ? AND source_version_id = ?",
        (tenant_id, source_version_id),
    ).fetchone()
    if existing:
        row = _row_dict(existing) or {}
        if (
            str(row.get("document_id") or "") != str(document.get("id") or "")
            or str(row.get("document_version_id") or "") != str(version.get("id") or "")
            or str(row.get("content_hash") or "") != content_hash
        ):
            raise DocumentVersionError("DOCUMENT_SOURCE_OBSERVATION_CONFLICT", "source version is already linked to another document fact", status_code=409)
        cursor.execute(
            "UPDATE kb_document_source SET observed_at = ?, observation_count = observation_count + 1, updated_at = ?, updated_by = ? WHERE id = ? AND tenant_id = ?",
            (now, now, actor, row["id"], tenant_id),
        )
        return _row_dict(cursor.execute("SELECT * FROM kb_document_source WHERE id = ? AND tenant_id = ?", (row["id"], tenant_id)).fetchone()) or row
    observation_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO kb_document_source (
            id, tenant_id, document_id, document_version_id, source_registry_id,
            source_version_id, canonical_url, content_hash, observed_at,
            observation_count, metadata_json, status, created_at, updated_at,
            created_by, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'observed', ?, ?, ?, ?)
        """,
        (
            observation_id, tenant_id, str(document.get("id") or ""), str(version.get("id") or ""),
            str(source.get("id") or ""), source_version_id, canonical_url, content_hash, now,
            _json_db_value(metadata), now, now, actor, actor,
        ),
    )
    return _row_dict(cursor.execute("SELECT * FROM kb_document_source WHERE id = ? AND tenant_id = ?", (observation_id, tenant_id)).fetchone()) or {}


def _validate_inputs(source: dict[str, Any], source_version: dict[str, Any], user: dict[str, Any]) -> tuple[str, str, str, str, str, int]:
    tenant_id = _tenant(user)
    source_tenant = str(source.get("tenant_id") or "").strip()
    if source_tenant != tenant_id:
        raise DocumentVersionError("DOCUMENT_TENANT_CONFLICT", "source and actor tenant do not match", status_code=403)
    source_id = _safe_text(source.get("id"), field="source_registry_id", maximum=256, required=True)
    source_version_id = _safe_text(source_version.get("id"), field="source_version_id", maximum=256, required=True)
    if str(source_version.get("tenant_id") or tenant_id) != tenant_id or str(source_version.get("source_registry_id") or source_id) != source_id:
        raise DocumentVersionError("DOCUMENT_SOURCE_CONFLICT", "source version is outside the source tenant boundary", status_code=403)
    canonical_url = _canonical_url(source.get("canonical_url"))
    content_hash = _safe_text(source_version.get("content_hash"), field="content_hash", maximum=64, required=True).lower()
    if not _SHA256_RE.fullmatch(content_hash):
        raise DocumentVersionError("DOCUMENT_HASH_INVALID", "content_hash must be a lowercase SHA-256 digest")
    try:
        byte_size = int(source_version.get("byte_size"))
    except (TypeError, ValueError) as exc:
        raise DocumentVersionError("DOCUMENT_BYTE_SIZE_INVALID", "byte_size must be a non-negative integer") from exc
    if byte_size < 0:
        raise DocumentVersionError("DOCUMENT_BYTE_SIZE_INVALID", "byte_size must be a non-negative integer")
    if not authorize_resource(user, "knowledge_source", "create", tenant_id=tenant_id):
        raise DocumentVersionError("DOCUMENT_PERMISSION_DENIED", "Insufficient permission for document version write", status_code=403)
    return tenant_id, source_id, source_version_id, canonical_url, content_hash, byte_size


def _load_authoritative_source_facts(
    cursor,
    *,
    tenant_id: str,
    source_id: str,
    source_version_id: str,
    supplied_url: str,
    supplied_hash: str,
    supplied_byte_size: int,
) -> tuple[dict[str, Any], dict[str, Any], str, str, int]:
    """Load immutable source facts instead of trusting caller-provided dicts."""
    source_row = cursor.execute(
        "SELECT * FROM kb_source_registry WHERE tenant_id = ? AND id = ?",
        (tenant_id, source_id),
    ).fetchone()
    if not source_row:
        raise DocumentVersionError("DOCUMENT_SOURCE_NOT_FOUND", "source registry fact was not found", status_code=404)
    version_row = cursor.execute(
        "SELECT * FROM kb_source_version WHERE tenant_id = ? AND id = ?",
        (tenant_id, source_version_id),
    ).fetchone()
    if not version_row:
        raise DocumentVersionError("DOCUMENT_SOURCE_VERSION_NOT_FOUND", "source version fact was not found", status_code=404)
    authoritative_source = _row_dict(source_row) or {}
    authoritative_version = _row_dict(version_row) or {}
    if str(authoritative_version.get("source_registry_id") or "") != source_id:
        raise DocumentVersionError("DOCUMENT_SOURCE_CONFLICT", "source version is outside the source registry boundary", status_code=403)
    authoritative_url = _canonical_url(authoritative_source.get("canonical_url"))
    authoritative_hash = _safe_text(
        authoritative_version.get("content_hash"),
        field="content_hash",
        maximum=64,
        required=True,
    ).lower()
    if not _SHA256_RE.fullmatch(authoritative_hash):
        raise DocumentVersionError("DOCUMENT_SOURCE_FACT_INVALID", "source version hash is invalid", status_code=409)
    try:
        authoritative_byte_size = int(authoritative_version.get("byte_size"))
    except (TypeError, ValueError) as exc:
        raise DocumentVersionError("DOCUMENT_SOURCE_FACT_INVALID", "source version byte size is invalid", status_code=409) from exc
    if authoritative_byte_size < 0:
        raise DocumentVersionError("DOCUMENT_SOURCE_FACT_INVALID", "source version byte size is invalid", status_code=409)
    if supplied_url != authoritative_url or supplied_hash != authoritative_hash or supplied_byte_size != authoritative_byte_size:
        raise DocumentVersionError("DOCUMENT_SOURCE_FACT_MISMATCH", "source version facts do not match the registry", status_code=409)
    return authoritative_source, authoritative_version, authoritative_url, authoritative_hash, authoritative_byte_size


def _audit_document_version(*, user: dict[str, Any], tenant_id: str, document: dict[str, Any], version: dict[str, Any], decision: str) -> None:
    # The audit payload contains only IDs, hashes and counts; no body or URL.
    try:
        event_type = {
            "merge_same_content_different_source": "document_source_merged",
            "replay_same_document_content": "document_version_replayed",
        }.get(decision, "document_version_added")
        log_audit_event(
            event_type=event_type,
            category="knowledge_document",
            severity="info",
            status="success",
            summary="Knowledge document version decision recorded",
            actor_id=_actor(user),
            actor_username=str(user.get("username") or _actor(user))[:256],
            actor_role=str(user.get("role") or "system")[:64],
            target_type="kb_document_version",
            target_id=str(version.get("id") or ""),
            details={
                "tenant_id": tenant_id,
                "decision": decision,
                "document_id": str(document.get("id") or ""),
                "document_version_id": str(version.get("id") or ""),
                "version_no": int(version.get("version_no") or 0),
                "content_hash": str(version.get("content_hash") or ""),
            },
        )
    except Exception:
        # The fact transaction is already committed.  Never expose a logging
        # provider/connection error or roll back an immutable version fact.
        return


def record_document_version(
    source: dict[str, Any],
    source_version: dict[str, Any],
    user: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    original_content: str | bytes | None = None,
    normalized_content: str | None = None,
    collection_id: str | None = None,
    document_kind: str = "official_manual",
) -> dict[str, Any]:
    """Append or replay a V2 document version for one immutable source fact."""
    tenant_id, source_id, source_version_id, canonical_url, content_hash, byte_size = _validate_inputs(source, source_version, user)
    document_kind = _safe_text(document_kind, field="document_kind", maximum=64) or "official_manual"
    if document_kind not in {"official_manual", "product_registry", "command_reference", "configuration", "cli_output", "troubleshooting", "example", "enterprise_sop", "user_note"}:
        raise DocumentVersionError("DOCUMENT_KIND_INVALID", "document_kind is not allowlisted")
    source_kind = _safe_text(source.get("source_kind") or "official_url", field="source_kind", maximum=64)
    collection = _safe_text(collection_id or "legacy-default", field="collection_id", maximum=256, required=True)
    safe_metadata = _safe_metadata(metadata)
    actor = _actor(user)
    parser_name = _safe_text(source_version.get("parser_name"), field="parser_name", maximum=128, required=True)
    parser_version = _safe_text(source_version.get("parser_version"), field="parser_version", maximum=64, required=True)
    trust_level = str(source.get("trust_level") or "official").strip().lower()
    if trust_level not in _TRUST_LEVELS:
        raise DocumentVersionError("DOCUMENT_TRUST_INVALID", "trust_level is not allowlisted")
    original_ref = _safe_text(source_version.get("raw_content_ref") or "", field="original_content_ref", maximum=4096)
    if original_content is None and not original_ref:
        # The outbound boundary intentionally does not return raw bytes.  A
        # stable opaque reference proves where the immutable source fact lives.
        original_ref = f"source-version://{source_version_id}"
    if isinstance(original_content, bytes):
        try:
            original_text = original_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentVersionError("DOCUMENT_CONTENT_INVALID", "original_content must be UTF-8") from exc
    elif original_content is None:
        original_text = ""
    else:
        original_text = str(original_content)
    if original_content is not None and hashlib.sha256(original_text.encode("utf-8")).hexdigest() != content_hash:
        raise DocumentVersionError("DOCUMENT_HASH_MISMATCH", "original_content does not match source content hash")
    if original_content is not None and len(original_text.encode("utf-8")) != byte_size:
        raise DocumentVersionError("DOCUMENT_BYTE_SIZE_MISMATCH", "original_content does not match source byte_size")
    normalized_text = str(normalized_content or "") if normalized_content is not None else ""
    now = _now()
    document_id = ""
    decision = "new_version"
    document: dict[str, Any] = {}
    version: dict[str, Any] = {}
    source_observation: dict[str, Any] = {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Source Registry and Source Version are the authority for URL,
        # parser, trust, hash, and byte-size facts.  The adapter may pass
        # ordinary dictionaries, but their mutable fields must not influence
        # cross-URL deduplication or the immutable V2 record.
        source, source_version, canonical_url, content_hash, byte_size = _load_authoritative_source_facts(
            cursor,
            tenant_id=tenant_id,
            source_id=source_id,
            source_version_id=source_version_id,
            supplied_url=canonical_url,
            supplied_hash=content_hash,
            supplied_byte_size=byte_size,
        )
        source_kind = _safe_text(source.get("source_kind") or "official_url", field="source_kind", maximum=64)
        parser_name = _safe_text(source_version.get("parser_name"), field="parser_name", maximum=128, required=True)
        parser_version = _safe_text(source_version.get("parser_version"), field="parser_version", maximum=64, required=True)
        trust_level = str(source.get("trust_level") or "official").strip().lower()
        if trust_level not in _TRUST_LEVELS:
            raise DocumentVersionError("DOCUMENT_SOURCE_FACT_INVALID", "source trust level is invalid", status_code=409)
        original_ref = _safe_text(source_version.get("raw_content_ref") or "", field="original_content_ref", maximum=4096)
        if original_content is None and not original_ref:
            original_ref = f"source-version://{source_version_id}"
        row = cursor.execute(
            "SELECT * FROM kb_document WHERE tenant_id = ? AND source_registry_id = ? AND canonical_key = ?",
            (tenant_id, source_id, canonical_url),
        ).fetchone()
        document = _row_dict(row) or {}
        if not document:
            # A different URL may point at an already-known immutable version.
            # Merge only when trust/parser/document-kind contracts match; the
            # source and source-version facts remain separately queryable.
            candidate_row = cursor.execute(
                """
                SELECT v.*
                FROM kb_document_version v
                WHERE v.tenant_id = ? AND v.content_hash = ?
                ORDER BY v.created_at ASC, v.id ASC
                LIMIT 1
                """,
                (tenant_id, content_hash),
            ).fetchone()
            if candidate_row:
                candidate_version = _row_dict(candidate_row) or {}
                candidate_document = _row_dict(
                    cursor.execute(
                        "SELECT * FROM kb_document WHERE tenant_id = ? AND id = ?",
                        (tenant_id, candidate_version.get("document_id")),
                    ).fetchone()
                ) or {}
                if _merge_compatible(
                    candidate_document,
                    candidate_version,
                    trust_level=trust_level,
                    parser_name=parser_name,
                    parser_version=parser_version,
                    document_kind=document_kind,
                ):
                    document = candidate_document
                    version = candidate_version
                    source_observation = _link_source_observation(
                        cursor,
                        tenant_id=tenant_id,
                        document=document,
                        version=version,
                        source=source,
                        source_version=source_version,
                        canonical_url=canonical_url,
                        content_hash=content_hash,
                        metadata=safe_metadata,
                        actor=actor,
                        now=now,
                    )
                    decision = "merge_same_content_different_source"
                    conn.commit()
                    decoded_document = _decode(document)
                    decoded_version = _decode(version)
                    _audit_document_version(user=user, tenant_id=tenant_id, document=decoded_document, version=decoded_version, decision=decision)
                    return {
                        "decision": decision,
                        "replayed": True,
                        "merged": True,
                        "changed": False,
                        "document": decoded_document,
                        "document_version": decoded_version,
                        "source_observation": _decode_observation(source_observation),
                    }
                decision = "new_document_same_content_incompatible_source"
        if not document:
            document_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO kb_document (
                    id, tenant_id, collection_id, source_registry_id, canonical_key,
                    title, document_kind, source_uri, trust_level, metadata_json,
                    source_kind, status, created_at, updated_at, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
                """,
                (
                    document_id, tenant_id, collection, source_id, canonical_url,
                    _safe_text(source.get("name") or canonical_url, field="title", maximum=512),
                    document_kind, canonical_url, trust_level, _json_db_value(safe_metadata),
                    source_kind, now, now, actor, actor,
                ),
            )
            document = _row_dict(cursor.execute("SELECT * FROM kb_document WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)).fetchone()) or {}
        else:
            document_id = str(document.get("id") or "")
            if str(document.get("collection_id") or collection) != collection:
                raise DocumentVersionError("DOCUMENT_COLLECTION_CONFLICT", "document collection boundary cannot change", status_code=409)
        existing = cursor.execute(
            "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? AND content_hash = ?",
            (tenant_id, document_id, content_hash),
        ).fetchone()
        if existing:
            version = _row_dict(existing) or {}
            source_observation = _link_source_observation(
                cursor,
                tenant_id=tenant_id,
                document=document,
                version=version,
                source=source,
                source_version=source_version,
                canonical_url=canonical_url,
                content_hash=content_hash,
                metadata=safe_metadata,
                actor=actor,
                now=now,
            )
            decision = "replay_same_document_content"
            conn.commit()
            decoded_document = _decode(document)
            decoded_version = _decode(version)
            _audit_document_version(user=user, tenant_id=tenant_id, document=decoded_document, version=decoded_version, decision="replay")
            return {
                "decision": decision,
                "replayed": True,
                "changed": False,
                "document": decoded_document,
                "document_version": decoded_version,
                "source_observation": _decode_observation(source_observation),
            }
        previous = cursor.execute(
            "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? ORDER BY version_no DESC LIMIT 1",
            (tenant_id, document_id),
        ).fetchone()
        previous_dict = _row_dict(previous) or {}
        version_no = int(previous_dict.get("version_no") or 0) + 1
        version_id = str(uuid.uuid4())
        status = "draft"
        metadata_hash = hashlib.sha256(_json_dumps(safe_metadata).encode("utf-8")).hexdigest()
        normalized_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() if normalized_text else ""
        fetched_at = _safe_text(source_version.get("fetched_at") or now, field="fetched_at", maximum=128, required=True)
        cursor.execute(
            """
            INSERT INTO kb_document_version (
                id, tenant_id, document_id, source_version_id, version_no,
                original_content, normalized_content, content_hash, metadata_json,
                metadata_hash, parser_name, parser_version, trust_level, acl_json,
                status, mime_type, byte_size, original_content_ref,
                normalized_content_hash, metadata_parse_status, metadata_parse_error,
                fetched_at, approved_by, supersedes_version_id, created_at,
                updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id, tenant_id, document_id, source_version_id, version_no,
                original_text, normalized_text, content_hash, _json_db_value(safe_metadata),
                metadata_hash, parser_name, parser_version, trust_level, _json_db_value({}),
                status, _safe_text(source_version.get("response_content_type") or "", field="mime_type", maximum=256),
                byte_size, original_ref, normalized_hash, str(safe_metadata.get("metadata_parse_status") or "missing"), "",
                fetched_at, "", str(previous_dict.get("id") or "") or None, now, now, actor, actor,
            ),
        )
        cursor.execute(
            "UPDATE kb_document SET current_version_id = ?, updated_at = ?, updated_by = ?, metadata_json = ? WHERE id = ? AND tenant_id = ?",
            (version_id, now, actor, _json_db_value(safe_metadata), document_id, tenant_id),
        )
        version = _row_dict(cursor.execute("SELECT * FROM kb_document_version WHERE id = ? AND tenant_id = ?", (version_id, tenant_id)).fetchone()) or {}
        document = _row_dict(cursor.execute("SELECT * FROM kb_document WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)).fetchone()) or document
        source_observation = _link_source_observation(
            cursor,
            tenant_id=tenant_id,
            document=document,
            version=version,
            source=source,
            source_version=source_version,
            canonical_url=canonical_url,
            content_hash=content_hash,
            metadata=safe_metadata,
            actor=actor,
            now=now,
        )
        conn.commit()
    decoded_document = _decode(document)
    decoded_version = _decode(version)
    _audit_document_version(user=user, tenant_id=tenant_id, document=decoded_document, version=decoded_version, decision=decision)
    return {
        "decision": decision,
        "replayed": False,
        "changed": bool(previous_dict),
        "document": decoded_document,
        "document_version": decoded_version,
        "source_observation": _decode_observation(source_observation),
    }


def list_document_versions(document_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "read", tenant_id=tenant_id):
        raise DocumentVersionError("DOCUMENT_PERMISSION_DENIED", "Insufficient permission for document version read", status_code=403)
    document_id = _safe_text(document_id, field="document_id", maximum=256, required=True)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? ORDER BY version_no DESC",
            (tenant_id, document_id),
        ).fetchall()
        return [_decode(_row_dict(row) or {}) for row in rows]


def compare_document_versions(
    document_id: str,
    left_version_id: str,
    right_version_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Return a bounded, metadata-only comparison for two tenant versions.

    Bodies are intentionally never returned by this endpoint.  The UI gets
    hashes, parser/size changes, and line-level counts sufficient to decide
    whether a publish/supersede action is warranted without creating a new
    content exfiltration surface.
    """
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "read", tenant_id=tenant_id):
        raise DocumentVersionError("DOCUMENT_PERMISSION_DENIED", "Insufficient permission for document version read", status_code=403)
    document_id = _safe_text(document_id, field="document_id", maximum=256, required=True)
    left_id = _safe_text(left_version_id, field="left_version_id", maximum=256, required=True)
    right_id = _safe_text(right_version_id, field="right_version_id", maximum=256, required=True)
    if left_id == right_id:
        raise DocumentVersionError("DOCUMENT_COMPARE_SAME_VERSION", "two different versions are required", status_code=400)

    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        metadata = _json_load(row.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "id": str(row.get("id") or ""),
            "version_no": int(row.get("version_no") or 0),
            "status": str(row.get("status") or ""),
            "lifecycle_status": str(row.get("lifecycle_status") or row.get("status") or ""),
            "content_hash": str(row.get("content_hash") or ""),
            "metadata_hash": str(row.get("metadata_hash") or ""),
            "normalized_content_hash": str(row.get("normalized_content_hash") or ""),
            "byte_size": int(row.get("byte_size") or 0),
            "parser_name": str(row.get("parser_name") or ""),
            "parser_version": str(row.get("parser_version") or ""),
            "trust_level": str(row.get("trust_level") or ""),
            "metadata_keys": sorted(str(key) for key in metadata.keys())[:100],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    with get_db_connection() as conn:
        rows = []
        for version_id in (left_id, right_id):
            row = _row_dict(conn.execute(
                "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? AND id = ?",
                (tenant_id, document_id, version_id),
            ).fetchone())
            if not row:
                raise DocumentVersionError("DOCUMENT_VERSION_NOT_FOUND", "document version was not found", status_code=404)
            rows.append(row)

    left, right = rows
    left_summary, right_summary = _summary(left), _summary(right)
    comparable_fields = (
        "content_hash", "metadata_hash", "normalized_content_hash", "byte_size",
        "parser_name", "parser_version", "trust_level", "metadata_keys",
    )
    changed_fields = [field for field in comparable_fields if left_summary.get(field) != right_summary.get(field)]
    left_content = str(left.get("normalized_content") or "")
    right_content = str(right.get("normalized_content") or "")
    # Avoid unbounded diff work if a caller compares very large retained
    # documents; hashes and sizes still provide an exact change signal.
    max_diff_bytes = 2 * 1024 * 1024
    if len(left_content.encode("utf-8")) <= max_diff_bytes and len(right_content.encode("utf-8")) <= max_diff_bytes:
        left_lines, right_lines = left_content.splitlines(), right_content.splitlines()
        matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines, autojunk=False)
        added = removed = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                removed += i2 - i1
            if tag in {"replace", "insert"}:
                added += j2 - j1
        diff_available = True
    else:
        left_lines = right_lines = []
        added = removed = 0
        diff_available = False
    return {
        "document_id": document_id,
        "left": left_summary,
        "right": right_summary,
        "changed_fields": changed_fields,
        "content_changed": left_summary["content_hash"] != right_summary["content_hash"],
        "metadata_changed": left_summary["metadata_hash"] != right_summary["metadata_hash"],
        "line_diff": {
            "available": diff_available,
            "left_lines": len(left_lines),
            "right_lines": len(right_lines),
            "added_lines": added,
            "removed_lines": removed,
        },
        "raw_content_included": False,
    }


__all__ = ["DocumentVersionError", "record_document_version", "list_document_versions", "compare_document_versions"]
