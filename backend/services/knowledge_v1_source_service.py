"""V1 knowledge-source service backed only by the V1 document projection.

``ai_document`` is used as the source identity/document row and
``ai_document_revision`` stores immutable fetch facts plus refresh observations.
The module intentionally keeps the public source-service contract small so the
ingestion and API layers do not need a second catalog schema.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import SplitResult, urlsplit, urlunsplit

import yaml

import database as _database
from core.rbac import authorize_resource
from database import get_db_connection
from services.audit_service import log_audit_event
from services.source_version_manifest_service import SourceVersionManifestError, build_source_version_manifest


REGISTRY_STATUSES = {"draft", "active", "disabled", "archived", "deleted", "quarantined", "purged"}
VERSION_STATUSES = REGISTRY_STATUSES | {"fetched", "verified", "failed", "observed"}
SOURCE_TYPES = {"official_vendor", "official_product", "enterprise", "internal", "user_upload", "api"}
SOURCE_KINDS = {
    "official_url", "product_page", "configuration_guide", "command_reference",
    "release_note", "troubleshooting_guide", "product_support", "enterprise",
    "internal", "user_upload", "api",
}
TRUST_LEVELS = {"official", "reviewed", "internal", "untrusted"}
_OFFICIAL_KINDS = {
    "official_url", "product_page", "configuration_guide", "command_reference",
    "release_note", "troubleshooting_guide", "product_support",
}
_CAT_SOURCE_KIND_TO_TYPE = {
    "official_url": "official_vendor",
    "product_page": "official_product",
    "configuration_guide": "official_product",
    "command_reference": "official_product",
    "release_note": "official_product",
    "troubleshooting_guide": "official_product",
    "product_support": "official_product",
}
_TYPE_DEFAULT_KIND = {
    "official_vendor": "official_url",
    "official_product": "product_page",
    "enterprise": "enterprise",
    "internal": "internal",
    "user_upload": "user_upload",
    "api": "api",
}
_SENSITIVE_KEY_PARTS = {
    "password", "passwd", "token", "secret", "private_key", "authorization",
    "cookie", "api_key", "apikey", "credential",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_METADATA_BYTES = 256 * 1024
_DEFAULT_COLLECTION_POLICY: dict[str, Any] = {
    "http_methods": ["GET", "HEAD"],
    "user_agent": "NexoraKnowledgeEngine/1.0",
    "timeout_seconds": 15,
    "max_bytes": 20_000_000,
    "redirect_limit": 3,
    "rate_limit_per_minute": 30,
    "robots_policy": "respect",
    "parser_name": "html",
    "parser_version": "1.0.0",
    "content_types": ["text/html", "text/plain", "application/pdf", "application/json", "application/xml"],
    "headers_allowlist": [],
    "retry_policy": {"max_attempts": 2, "retry_4xx": False, "retry_5xx": True},
}


class SourceRegistryError(ValueError):
    """Stable, user-safe source operation error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _row_dict(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)


def _json_load(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    # psycopg2.extras.Json is used for writes and can still be present on the
    # freshly-created row returned by a same-request path.  Decode its
    # adapted Python value instead of stringifying the adapter repr.
    adapted = getattr(value, "adapted", None)
    if adapted is not None and adapted is not value:
        return _json_load(adapted, default)
    if value is None or value == "":
        return copy.deepcopy(default if default is not None else {})
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(default if default is not None else {})


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _db_json(value: Any) -> Any:
    value = value if isinstance(value, (dict, list)) else {}
    if _database._USE_PG:
        try:
            from psycopg2.extras import Json

            return Json(value, dumps=lambda item: _json_dumps(item))
        except ImportError:
            pass
    return _json_dumps(value)


def _assert_no_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                raise SourceRegistryError(
                    "SECRET_FIELD_FORBIDDEN",
                    f"Secret-bearing field is not allowed in {path or 'source metadata'}",
                    details={"field": path + ("." if path else "") + str(key)},
                )
            _assert_no_secrets(item, path + ("." if path else "") + str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "bearer " in lowered or "basic " in lowered:
            raise SourceRegistryError("SECRET_VALUE_FORBIDDEN", "Authorization material is not allowed in source metadata")


def _canonicalize_url(value: Any) -> tuple[str, str, int, str]:
    raw = _text(value)
    if not raw or len(raw) > 4096 or _CONTROL_RE.search(raw):
        raise SourceRegistryError("INVALID_URL", "canonical_url must be a bounded absolute URL")
    try:
        parsed: SplitResult = urlsplit(raw)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise SourceRegistryError("INVALID_URL", "canonical_url has an invalid host or port") from exc
    if parsed.scheme.lower() != "https":
        raise SourceRegistryError("URL_SCHEME_FORBIDDEN", "Only HTTPS source URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise SourceRegistryError("URL_USERINFO_FORBIDDEN", "URL userinfo is not allowed")
    if parsed.fragment:
        raise SourceRegistryError("URL_FRAGMENT_FORBIDDEN", "URL fragments are not part of source identity")
    if parsed.query:
        raise SourceRegistryError("URL_QUERY_FORBIDDEN", "Query parameters are not allowed in source identity")
    if not host:
        raise SourceRegistryError("INVALID_URL", "canonical_url must include a hostname")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise SourceRegistryError("INVALID_URL", "Hostname is not valid IDNA") from exc
    if "*" in host or host.startswith("."):
        raise SourceRegistryError("WILDCARD_HOST_FORBIDDEN", "Wildcard hosts are not allowed")
    if port not in (None, 443):
        raise SourceRegistryError("URL_PORT_FORBIDDEN", "Only HTTPS port 443 is accepted")
    path = parsed.path or "/"
    if "\\" in path or re.search(r"(?i)%2e|%2f|%5c", path):
        raise SourceRegistryError("URL_PATH_ENCODING_FORBIDDEN", "Encoded path traversal or separators are not allowed")
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
    canonical = urlunsplit(("https", host, normalized_path or "/", "", ""))
    return canonical, host, 443, normalized_path or "/"


def _load_official_allowlist() -> dict[str, list[dict[str, Any]]]:
    architecture_dir = Path(__file__).resolve().parents[2] / "docs" / "knowledge-engine" / "architecture"
    paths = [
        architecture_dir / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml",
        architecture_dir / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST-EXTENSIONS.yaml",
    ]
    entries: dict[str, list[dict[str, Any]]] = {}
    for index, path in enumerate(paths):
        if index == 1 and not path.exists():
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise SourceRegistryError("ALLOWLIST_UNAVAILABLE", "Official source allowlist is unavailable", status_code=503) from exc
        for vendor in document.get("vendor_entries") or []:
            vendor_name = _text(vendor.get("vendor"))
            for host_entry in vendor.get("official_hosts") or []:
                host = _text(host_entry.get("host")).lower()
                if not host or "*" in host:
                    continue
                entries.setdefault(host, []).append(
                    {
                        "vendor": vendor_name,
                        "vendor_key": _text(vendor.get("vendor_key")),
                        "product_family": _text(vendor.get("product_family")),
                        "platform_code": _text(vendor.get("platform_code")),
                        "os_family": _text(vendor.get("os_family")),
                        "path_prefixes": [_text(item) for item in host_entry.get("path_prefixes") or []],
                        "allowed_source_kinds": set(_text(item) for item in vendor.get("allowed_source_kinds") or []),
                    }
                )
    return entries


def _normalize_type(source_type: Any, source_kind: Any = None) -> tuple[str, str]:
    raw_type = _text(source_type).lower()
    raw_kind = _text(source_kind).lower()
    if raw_type in _CAT_SOURCE_KIND_TO_TYPE:
        mapped_type = _CAT_SOURCE_KIND_TO_TYPE[raw_type]
        if raw_kind and raw_kind != raw_type:
            raise SourceRegistryError("SOURCE_TYPE_KIND_MISMATCH", "source_type and source_kind describe different source classes")
        return mapped_type, raw_type
    if raw_type not in SOURCE_TYPES:
        raise SourceRegistryError("UNKNOWN_SOURCE_TYPE", "source_type is not in the source allowlist")
    if not raw_kind:
        raw_kind = _TYPE_DEFAULT_KIND[raw_type]
    if raw_kind not in SOURCE_KINDS:
        raise SourceRegistryError("UNKNOWN_SOURCE_KIND", "source_kind is not in the source taxonomy")
    if raw_kind in _CAT_SOURCE_KIND_TO_TYPE and _CAT_SOURCE_KIND_TO_TYPE[raw_kind] != raw_type:
        raise SourceRegistryError("SOURCE_TYPE_KIND_MISMATCH", "source_kind is incompatible with source_type")
    return raw_type, raw_kind


def _normalize_metadata(value: Any, *, user: dict[str, Any], source_type: str, now: str) -> dict[str, Any]:
    if value is None:
        metadata: dict[str, Any] = {}
    elif isinstance(value, dict):
        metadata = copy.deepcopy(value)
    else:
        raise SourceRegistryError("INVALID_METADATA", "metadata must be an object")
    _assert_no_secrets(metadata)
    if source_type in {"official_vendor", "official_product"}:
        metadata.setdefault("reviewer", _text(user.get("username") or _actor(user)))
        metadata.setdefault("reviewed_at", now)
        metadata.setdefault("terms_review_status", "pending")
    if len(_json_dumps(metadata).encode("utf-8")) > _MAX_METADATA_BYTES:
        raise SourceRegistryError("METADATA_TOO_LARGE", "metadata exceeds the 256 KiB limit")
    return metadata


def _normalize_policy(value: Any) -> dict[str, Any]:
    if value is None:
        policy = copy.deepcopy(_DEFAULT_COLLECTION_POLICY)
    elif isinstance(value, dict):
        policy = copy.deepcopy(_DEFAULT_COLLECTION_POLICY)
        policy.update(copy.deepcopy(value))
    else:
        raise SourceRegistryError("INVALID_COLLECTION_POLICY", "collection_policy must be an object")
    _assert_no_secrets(policy)
    methods = [_text(item).upper() for item in policy.get("http_methods") or []]
    if not methods or any(item not in {"GET", "HEAD"} for item in methods):
        raise SourceRegistryError("HTTP_METHOD_FORBIDDEN", "collection_policy.http_methods may contain only GET and HEAD")
    if len(set(methods)) != len(methods):
        raise SourceRegistryError("HTTP_METHOD_DUPLICATE", "collection_policy.http_methods must not contain duplicates")
    policy["http_methods"] = methods
    user_agent = _text(policy.get("user_agent"))
    if not user_agent or len(user_agent) > 256 or _CONTROL_RE.search(user_agent):
        raise SourceRegistryError("INVALID_USER_AGENT", "collection_policy.user_agent is required and bounded")
    try:
        timeout = int(policy.get("timeout_seconds"))
        max_bytes = int(policy.get("max_bytes"))
        redirect_limit = int(policy.get("redirect_limit"))
        rate_limit = int(policy.get("rate_limit_per_minute"))
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError("INVALID_COLLECTION_POLICY", "collection policy numeric limits must be integers") from exc
    if not 1 <= timeout <= 120:
        raise SourceRegistryError("INVALID_TIMEOUT", "timeout_seconds must be between 1 and 120")
    if not 1_024 <= max_bytes <= 100_000_000:
        raise SourceRegistryError("INVALID_MAX_BYTES", "max_bytes must be between 1 KiB and 100 MB")
    if not 0 <= redirect_limit <= 10:
        raise SourceRegistryError("INVALID_REDIRECT_LIMIT", "redirect_limit must be between 0 and 10")
    if not 1 <= rate_limit <= 100_000:
        raise SourceRegistryError("INVALID_RATE_LIMIT", "rate_limit_per_minute must be positive and bounded")
    policy["timeout_seconds"] = timeout
    policy["max_bytes"] = max_bytes
    policy["redirect_limit"] = redirect_limit
    policy["rate_limit_per_minute"] = rate_limit
    parser_name = _text(policy.get("parser_name"))
    parser_version = _text(policy.get("parser_version"))
    if not parser_name or not parser_version or len(parser_name) > 128 or len(parser_version) > 64:
        raise SourceRegistryError("PARSER_PIN_REQUIRED", "parser_name and parser_version are required")
    policy["parser_name"] = parser_name
    policy["parser_version"] = parser_version
    robots_policy = _text(policy.get("robots_policy")).lower()
    if robots_policy not in {"respect", "ignore_with_review", "not_applicable"}:
        raise SourceRegistryError("INVALID_ROBOTS_POLICY", "robots_policy must be explicit")
    policy["robots_policy"] = robots_policy
    retry = policy.get("retry_policy")
    if not isinstance(retry, dict):
        raise SourceRegistryError("INVALID_RETRY_POLICY", "retry_policy must be an object")
    try:
        max_attempts = int(retry.get("max_attempts", 2))
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError("INVALID_RETRY_POLICY", "retry_policy.max_attempts must be an integer") from exc
    if not 1 <= max_attempts <= 3 or bool(retry.get("retry_4xx", False)):
        raise SourceRegistryError("RETRY_POLICY_FORBIDDEN", "retries must be bounded and 4xx retries are forbidden")
    policy["retry_policy"] = {"max_attempts": max_attempts, "retry_4xx": False, "retry_5xx": bool(retry.get("retry_5xx", True))}
    return policy


def _policy_hash(policy: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(policy).encode("utf-8")).hexdigest()


def _tenant_for_user(user: dict[str, Any], requested: str | None = None, *, allow_all: bool = False) -> str | None:
    user_tenant = _text(user.get("tenant_id"))
    role = _text(user.get("role"))
    requested = _text(requested) or None
    if role != "Administrator" and _text(user.get("role_profile")) != "System Administrator":
        tenant = user_tenant or "tenant-default"
        if requested and requested != tenant:
            raise SourceRegistryError("TENANT_SCOPE_DENIED", "Request tenant is outside the authenticated tenant scope", status_code=403)
        return tenant
    if requested:
        return requested
    if user_tenant:
        return user_tenant
    return None if allow_all else "tenant-default"


def _authorize(user: dict[str, Any], action: str, tenant_id: str | None) -> None:
    if not authorize_resource(user, "knowledge_source", action, tenant_id=tenant_id):
        raise SourceRegistryError("SOURCE_PERMISSION_DENIED", "Insufficient permission for this source operation", status_code=403)


def _table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _knowledge_base_id(conn, tenant_id: str) -> str:
    row = conn.execute(
        "SELECT id FROM ai_knowledge_base WHERE tenant_id = ? AND enabled = 1 ORDER BY created_at, id LIMIT 1",
        (tenant_id,),
    ).fetchone()
    if row:
        return _text(row[0])
    row = conn.execute("SELECT id FROM ai_knowledge_base ORDER BY created_at, id LIMIT 1").fetchone()
    if row:
        return _text(row[0])
    # Fresh installations may not have created the first UI-visible KB yet.
    # Source registration is still a normal V1 document write, so create the
    # same minimal default that the document service uses.
    kb_id = "kb_" + uuid.uuid4().hex[:12]
    now = _now()
    columns = _table_columns(conn, "ai_knowledge_base")
    values = {
        "id": kb_id,
        "name": "Default KB",
        "description": "Enterprise network knowledge base",
        "enabled": 1,
        "created_by": "system",
        "tenant_id": tenant_id,
        "acl_json": _db_json({}),
        "created_at": now,
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    names = list(filtered)
    conn.execute(
        f"INSERT INTO ai_knowledge_base ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(filtered[name] for name in names),
    )
    return kb_id


def _source_row(conn, source_id: str, user: dict[str, Any], *, tenant_id: str | None = None) -> dict[str, Any] | None:
    scoped_tenant = _tenant_for_user(user, tenant_id)
    params: list[Any] = []
    where = []
    if scoped_tenant:
        where.append("d.tenant_id = ?")
        params.append(scoped_tenant)
    source_id = _text(source_id)
    where.append("d.id = ?")
    params.append(source_id)
    row = conn.execute(
        "SELECT d.* FROM ai_document d WHERE " + " AND ".join(where) + " LIMIT 1",
        tuple(params),
    ).fetchone()
    if row:
        return _row_dict(row)
    if scoped_tenant:
        legacy = conn.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_source_id = ? "
            "ORDER BY CASE WHEN record_type = 'document_revision' THEN 0 ELSE 1 END, revision_no LIMIT 1",
            (scoped_tenant, source_id),
        ).fetchone()
        if legacy:
            row = conn.execute(
                "SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?",
                (scoped_tenant, _text(legacy[0])),
            ).fetchone()
            if row:
                return _row_dict(row)
    return None


def _decode_source(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _json_load(row.get("metadata_json"), {})
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        policy = _normalize_policy(metadata.get("collection_policy"))
    except SourceRegistryError:
        policy = copy.deepcopy(_DEFAULT_COLLECTION_POLICY)
    canonical_url = _text(row.get("canonical_url")) or _text(row.get("source"))
    parts = urlsplit(canonical_url)
    source_kind = _text(row.get("source_kind")) or _text(metadata.get("source_kind")) or _text(row.get("knowledge_source_type"))
    source_type = _text(row.get("knowledge_source_type"))
    if source_type == "official_url":
        source_type = "official_vendor"
    result = dict(row)
    result.update(
        {
            "id": _text(row.get("id")),
            "tenant_id": _text(row.get("tenant_id")) or "tenant-default",
            "source_type": source_type or "internal",
            "source_kind": source_kind,
            "canonical_url": canonical_url,
            "allowed_host": _text(parts.hostname).lower(),
            "allowed_scheme": "https",
            "allowed_port": 443,
            "host_match_mode": "exact",
            "trust_level": _text(row.get("source_trust_level")) or "internal",
            "collection_policy": policy,
            "metadata": metadata,
            "validation": _json_load(metadata.get("validation"), {}),
            "validation_status": _text(row.get("source_validation_status")) or "unvalidated",
            "fetch_enabled": _text(row.get("status")) == "active" and _text(row.get("source_validation_status")) == "valid",
            "policy_version": int(metadata.get("policy_version") or 1),
            "policy_hash": _policy_hash(policy),
            "status": _text(row.get("status")) or "draft",
            "source_document_id": _text(row.get("id")),
        }
    )
    result.pop("metadata_json", None)
    return result


# Kept as a short-lived import compatibility name for callers that only need
# to decode a source-shaped row.  The implementation is V1-backed; it does
# not read the retired registry table.
def _decode_registry(row: Any) -> dict[str, Any] | None:
    return _decode_source(_row_dict(row) or {}) if row else None


def _get_source(source_id: str, user: dict[str, Any], *, tenant_id: str | None = None) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _source_row(conn, source_id, user, tenant_id=tenant_id)
        if not row:
            raise SourceRegistryError("SOURCE_NOT_FOUND", "Source was not found", status_code=404)
        return _decode_source(row)
    finally:
        conn.close()


def _audit(*, event_type: str, user: dict[str, Any], source: dict[str, Any], before: dict[str, Any] | None = None, after: dict[str, Any] | None = None, details: dict[str, Any] | None = None, conn=None) -> None:
    try:
        log_audit_event(
            event_type=event_type,
            category="knowledge_source",
            severity="info",
            status="success",
            summary=f"Knowledge source {event_type}",
            actor_id=_actor(user),
            actor_username=_text(user.get("username")) or "system",
            actor_role=_text(user.get("role")) or "system",
            target_type="knowledge_source",
            target_id=_text(source.get("id")),
            target_name=_text(source.get("name")),
            before=before,
            after=after,
            details=details or {},
            conn=conn,
        )
    except Exception:
        # Audit failure must not turn an already committed knowledge write into
        # an opaque API error; the source operation itself remains bounded.
        return


def _official_match(source: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any] | None]:
    canonical_url = _text(source.get("canonical_url"))
    parts = urlsplit(canonical_url)
    host = _text(parts.hostname).lower().rstrip(".")
    path = parts.path or "/"
    allowlist = _load_official_allowlist()
    entries = allowlist.get(host, [])
    reasons: list[str] = []
    for entry in entries:
        prefixes = [prefix for prefix in entry.get("path_prefixes") or [] if prefix]
        path_ok = not prefixes or any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)
        kind_ok = not entry.get("allowed_source_kinds") or _text(source.get("source_kind")) in entry["allowed_source_kinds"]
        if path_ok and kind_ok:
            return True, [], entry
        if not path_ok:
            reasons.append("path_outside_allowlist")
        if not kind_ok:
            reasons.append("source_kind_not_allowed")
    if not entries:
        reasons.append("host_not_allowlisted")
    return False, sorted(set(reasons)), None


def validate_official_url_input(url: Any, *, source_kind: Any = "official_url", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical, host, port, path = _canonicalize_url(url)
    kind = _text(source_kind).lower() or "official_url"
    if kind not in _OFFICIAL_KINDS:
        raise SourceRegistryError("UNKNOWN_SOURCE_KIND", "source_kind is not an official source kind")
    candidate = {"canonical_url": canonical, "source_kind": kind, "metadata": metadata or {}}
    match, reasons, entry = _official_match(candidate)
    return {
        "valid": bool(match),
        "canonical_url": canonical,
        "host": host,
        "port": port,
        "path": path,
        "source_kind": kind,
        "matched_catalog": entry or {},
        "reasons": reasons,
        "error_code": "" if match else "OFFICIAL_SOURCE_NOT_ALLOWLISTED",
    }


def create_source(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    source_type, source_kind = _normalize_type(payload.get("source_type"), payload.get("source_kind"))
    canonical_url, host, _port, _path = _canonicalize_url(payload.get("canonical_url"))
    metadata = _normalize_metadata(payload.get("metadata"), user=user, source_type=source_type, now=now)
    policy = _normalize_policy(payload.get("collection_policy"))
    metadata["collection_policy"] = policy
    metadata["source_kind"] = source_kind
    metadata["policy_version"] = 1
    tenant_id = _tenant_for_user(user)
    _authorize(user, "create", tenant_id)
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM ai_document WHERE tenant_id = ? AND (canonical_url = ? OR source = ?) ORDER BY created_at, id LIMIT 1",
            (tenant_id, canonical_url, canonical_url),
        ).fetchone()
        if existing:
            raise SourceRegistryError("SOURCE_URL_CONFLICT", "A source with this canonical URL already exists", status_code=409)
        source_id = "src-" + uuid.uuid4().hex
        columns = _table_columns(conn, "ai_document")
        values: dict[str, Any] = {
            "id": source_id,
            "knowledge_base_id": _knowledge_base_id(conn, tenant_id),
            "name": _text(payload.get("name")) or canonical_url,
            "source": canonical_url,
            "vendor": _text(metadata.get("vendor")) or "all",
            "platform": _text(metadata.get("platform_code")) or "all",
            "version": _text((metadata.get("version_scope") or {}).get("primary")) if isinstance(metadata.get("version_scope"), dict) else "",
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "tenant_id": tenant_id,
            "acl_json": _db_json({}),
            "source_trust_level": _text(payload.get("trust_level")) or ("official" if source_kind in _OFFICIAL_KINDS else "internal"),
            "knowledge_source_type": "official_url" if source_kind in _OFFICIAL_KINDS else source_type,
            "metadata_json": _db_json(metadata),
            "ingestion_status": "source_only",
            "canonical_url": canonical_url,
            "source_kind": source_kind,
            "source_validation_status": "unvalidated",
            "lifecycle_status": "draft",
            "lifecycle_revision": 0,
            "lifecycle_changed_by": _actor(user),
        }
        filtered = {key: value for key, value in values.items() if key in columns}
        names = list(filtered)
        conn.execute(
            f"INSERT INTO ai_document ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            tuple(filtered[name] for name in names),
        )
        conn.commit()
        result = _decode_source(_row_dict(conn.execute("SELECT * FROM ai_document WHERE id = ?", (source_id,)).fetchone()) or values)
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()
    _audit(event_type="source_created", user=user, source=result, after={"status": result.get("status"), "canonical_url": result.get("canonical_url")})
    return result


def list_sources(user: dict[str, Any], *, status: str = "all", tenant_id: str | None = None) -> list[dict[str, Any]]:
    scoped_tenant = _tenant_for_user(user, tenant_id, allow_all=True)
    _authorize(user, "read", scoped_tenant)
    conn = get_db_connection()
    try:
        params: list[Any] = []
        clauses = ["(d.canonical_url <> '' OR d.source <> '')"]
        if scoped_tenant:
            clauses.append("d.tenant_id = ?")
            params.append(scoped_tenant)
        if status and status != "all":
            clauses.append("d.status = ?")
            params.append(status)
        rows = conn.execute(
            "SELECT d.* FROM ai_document d WHERE " + " AND ".join(clauses) + " ORDER BY d.updated_at DESC, d.id",
            tuple(params),
        ).fetchall()
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            item = _decode_source(_row_dict(row) or {})
            key = (str(item.get("tenant_id") or ""), str(item.get("canonical_url") or ""))
            if key[1] and key in seen:
                continue
            if key[1]:
                seen.add(key)
            results.append(item)
        return results
    finally:
        conn.close()


def get_source(source_id: str, user: dict[str, Any], *, tenant_id: str | None = None) -> dict[str, Any]:
    return _get_source(source_id, user, tenant_id=tenant_id)


def update_source(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    tenant_id = _text(source.get("tenant_id"))
    _authorize(user, "update", tenant_id)
    now = _now()
    metadata = copy.deepcopy(source.get("metadata") or {})
    if payload.get("metadata") is not None:
        metadata = _normalize_metadata(payload.get("metadata"), user=user, source_type=_text(source.get("source_type")), now=now)
    policy_changed = payload.get("collection_policy") is not None
    if policy_changed:
        metadata["collection_policy"] = _normalize_policy(payload.get("collection_policy"))
    canonical_url = _text(source.get("canonical_url"))
    if payload.get("canonical_url") is not None:
        canonical_url = _canonicalize_url(payload.get("canonical_url"))[0]
        conn = get_db_connection()
        try:
            conflict = conn.execute(
                "SELECT 1 FROM ai_document WHERE tenant_id = ? AND canonical_url = ? AND id <> ? LIMIT 1",
                (tenant_id, canonical_url, _text(source_id)),
            ).fetchone()
        finally:
            conn.close()
        if conflict:
            raise SourceRegistryError("SOURCE_URL_CONFLICT", "A source with this canonical URL already exists", status_code=409)
    if policy_changed or payload.get("canonical_url") is not None or payload.get("metadata") is not None:
        metadata["policy_version"] = int(metadata.get("policy_version") or 1) + 1
    conn = get_db_connection()
    try:
        fields: dict[str, Any] = {
            "canonical_url": canonical_url,
            "source": canonical_url,
            "name": _text(payload.get("name")) if payload.get("name") is not None else source.get("name"),
            "source_trust_level": _text(payload.get("trust_level")) if payload.get("trust_level") is not None else source.get("trust_level"),
            "metadata_json": _db_json(metadata),
            "source_validation_status": "unvalidated" if (policy_changed or payload.get("canonical_url") is not None or payload.get("metadata") is not None) else source.get("validation_status"),
            "status": "disabled" if (policy_changed or payload.get("canonical_url") is not None or payload.get("metadata") is not None) else source.get("status"),
            "updated_at": now,
            "lifecycle_reason": "source policy or URL changed" if (policy_changed or payload.get("canonical_url") is not None) else source.get("lifecycle_reason"),
        }
        columns = _table_columns(conn, "ai_document")
        filtered = {key: value for key, value in fields.items() if key in columns}
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        conn.execute(
            f"UPDATE ai_document SET {assignments} WHERE tenant_id = ? AND id = ?",
            tuple(filtered.values()) + (tenant_id, _text(source_id)),
        )
        conn.commit()
        result = _decode_source(_row_dict(conn.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, _text(source_id))).fetchone()) or {})
    finally:
        conn.close()
    _audit(event_type="source_updated", user=user, source=result, after={"status": result.get("status"), "validation_status": result.get("validation_status")})
    return result


def validate_source(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    tenant_id = _text(source.get("tenant_id"))
    _authorize(user, "read", tenant_id)
    if _text(source.get("source_kind")) in _OFFICIAL_KINDS:
        valid, reasons, match = _official_match(source)
        result = {
            "valid": bool(valid),
            "canonical_url": _text(source.get("canonical_url")),
            "source_kind": _text(source.get("source_kind")),
            "matched_catalog": match or {},
            "reasons": reasons,
            "error_code": "" if valid else "OFFICIAL_SOURCE_NOT_ALLOWLISTED",
        }
    else:
        result = {"valid": True, "canonical_url": _text(source.get("canonical_url")), "source_kind": _text(source.get("source_kind")), "matched_catalog": {}, "reasons": [], "error_code": ""}
    conn = get_db_connection()
    try:
        metadata = copy.deepcopy(source.get("metadata") or {})
        metadata["validation"] = result
        conn.execute(
            "UPDATE ai_document SET source_validation_status = ?, metadata_json = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            ("valid" if result["valid"] else "invalid", _db_json(metadata), _now(), tenant_id, _text(source_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return result


def enable_source(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    _authorize(user, "update", _text(source.get("tenant_id")))
    validation = validate_source(source_id, user)
    if not validation.get("valid"):
        raise SourceRegistryError("SOURCE_VALIDATION_FAILED", "Source validation failed", status_code=409, details=validation)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE ai_document SET status = 'active', lifecycle_status = 'published', lifecycle_changed_at = ?, lifecycle_changed_by = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            (_now(), _actor(user), _now(), _text(source.get("tenant_id")), _text(source_id)),
        )
        conn.commit()
        return _decode_source(_row_dict(conn.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (_text(source.get("tenant_id")), _text(source_id))).fetchone()) or {})
    finally:
        conn.close()


def disable_source(source_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    source = get_source(source_id, user)
    _authorize(user, "update", _text(source.get("tenant_id")))
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE ai_document SET status = 'disabled', lifecycle_status = 'disabled', lifecycle_reason = ?, lifecycle_changed_at = ?, lifecycle_changed_by = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            (_text(reason), _now(), _actor(user), _now(), _text(source.get("tenant_id")), _text(source_id)),
        )
        conn.commit()
        return _decode_source(_row_dict(conn.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (_text(source.get("tenant_id")), _text(source_id))).fetchone()) or {})
    finally:
        conn.close()


def quarantine_source_for_change(source_id: str, user: dict[str, Any], *, detection_type: str, reason_code: str, replacement_url: str = "", refresh_observation_id: str = "") -> dict[str, Any]:
    source = get_source(source_id, user)
    _authorize(user, "update", _text(source.get("tenant_id")))
    conn = get_db_connection()
    try:
        metadata = copy.deepcopy(source.get("metadata") or {})
        metadata["last_change_detection"] = {"detection_type": _text(detection_type), "reason_code": _text(reason_code), "replacement_url": _text(replacement_url), "observation_id": _text(refresh_observation_id)}
        conn.execute(
            "UPDATE ai_document SET status = 'quarantined', lifecycle_status = 'quarantined', lifecycle_reason = ?, lifecycle_changed_at = ?, lifecycle_changed_by = ?, metadata_json = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            (_text(reason_code), _now(), _actor(user), _db_json(metadata), _now(), _text(source.get("tenant_id")), _text(source_id)),
        )
        conn.commit()
        return _decode_source(_row_dict(conn.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (_text(source.get("tenant_id")), _text(source_id))).fetchone()) or {})
    finally:
        conn.close()


def delete_source(source_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    return disable_source(source_id, user, reason=reason or "deleted")


def _source_revision_rows(conn, source: dict[str, Any]) -> list[dict[str, Any]]:
    params = (_text(source.get("tenant_id")), _text(source.get("source_document_id") or source.get("id")))
    # New V1 writes keep the fetch manifest separate from the searchable
    # document revision.  The fallback keeps sources migrated from the old
    # model readable until their first post-migration refresh creates a V1
    # source_version record.
    rows = conn.execute(
        "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
        "AND record_type = 'source_version' ORDER BY revision_no DESC, created_at DESC, id DESC",
        params,
    ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'document_revision' AND legacy_source_version_id <> '' "
            "ORDER BY revision_no DESC, created_at DESC, id DESC",
            params,
        ).fetchall()
    return [_row_dict(row) or {} for row in rows]


def _decode_revision(row: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    fetch_metadata = _json_load(row.get("fetch_metadata_json"), {})
    manifest = _json_load(row.get("metadata_json"), {})
    if not isinstance(manifest, dict):
        manifest = {}
    source_manifest = manifest.get("source_manifest") if isinstance(manifest.get("source_manifest"), dict) else {}
    raw_manifest = source_manifest.get("raw_content") if isinstance(source_manifest.get("raw_content"), dict) else {}
    raw_storage = _text(raw_manifest.get("storage"))
    if not raw_storage:
        raw_storage = "hash_only_memory_boundary" if _text(row.get("record_type")) == "source_version" else "v1_document_revision"
    return {
        "id": _text(row.get("id")),
        "source_version_id": _text(row.get("id")),
        "source_registry_id": _text(row.get("legacy_source_id")) or _text(source.get("id")),
        "document_id": _text(row.get("document_id")),
        "tenant_id": _text(row.get("tenant_id")),
        "version_no": int(
            (_json_load(row.get("metadata_json"), {}) or {}).get(
                "source_version_no" if _text(row.get("record_type")) == "source_version" else "document_version_no",
                row.get("revision_no") or 1,
            )
            or row.get("revision_no")
            or 1
        ),
        "fetched_at": row.get("fetched_at"),
        "content_hash": _text(row.get("content_hash")),
        "byte_size": int(row.get("byte_size") or 0),
        "parser_name": _text(row.get("parser_name")),
        "parser_version": _text(row.get("parser_version")),
        "source_etag": _text(row.get("source_etag")),
        "source_last_modified": _text(row.get("source_last_modified")),
        "fetch_url": _text(row.get("fetch_url")),
        "response_content_type": _text(row.get("mime_type")),
        "http_status": row.get("http_status"),
        "raw_content_ref": _text(row.get("source_raw_content_ref")),
        "raw_content_storage": raw_storage,
        "verified_at": None,
        "verification_method": _text(fetch_metadata.get("verification_method")),
        "error_code": _text(row.get("error_code")),
        "metadata": _json_load(row.get("metadata_json"), {}),
        "status": _text(row.get("status")) or "fetched",
        "original_content": _text(row.get("original_content")),
        "original_content_ref": _text(row.get("source_raw_content_ref"))
        or (f"source-version://{_text(row.get('legacy_source_version_id') or row.get('id'))}" if not _text(row.get("original_content")) else ""),
        "normalized_content": _text(row.get("normalized_content")),
        "normalized_content_hash": _text(row.get("normalized_content_hash")),
        "supersedes_version_id": _text(manifest.get("supersedes_version_id")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("created_at"),
    }


def record_source_version(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    tenant_id = _text(source.get("tenant_id"))
    _authorize(user, "create", tenant_id)
    if _text(source.get("status")) != "active":
        raise SourceRegistryError("SOURCE_NOT_ACTIVE", "Source must be active before recording a version", status_code=409)
    if not source.get("fetch_enabled"):
        raise SourceRegistryError("SOURCE_NOT_VALIDATED", "Source must pass validation before recording a version", status_code=409)
    content = payload.get("content")
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    elif isinstance(content, (bytes, bytearray, memoryview)):
        content_bytes = bytes(content)
    else:
        content_bytes = None
    supplied_hash = _text(payload.get("content_hash")).lower()
    computed_hash = hashlib.sha256(content_bytes).hexdigest() if content_bytes is not None else ""
    content_hash = supplied_hash or computed_hash
    if not content_hash or not _SHA256_RE.fullmatch(content_hash):
        raise SourceRegistryError("INVALID_CONTENT_HASH", "content_hash must be a lowercase SHA-256 digest")
    if content_bytes is not None and computed_hash != content_hash:
        raise SourceRegistryError("CONTENT_HASH_MISMATCH", "content_hash does not match content")
    byte_size = int(payload.get("byte_size") if payload.get("byte_size") is not None else len(content_bytes or b""))
    if byte_size < 0 or byte_size > 100_000_000:
        raise SourceRegistryError("INVALID_BYTE_SIZE", "byte_size is outside the allowed range")
    if content_bytes is not None and byte_size != len(content_bytes):
        raise SourceRegistryError("CONTENT_SIZE_MISMATCH", "byte_size does not match content")
    parser_name = _text(payload.get("parser_name"))
    parser_version = _text(payload.get("parser_version"))
    if not parser_name or not parser_version:
        raise SourceRegistryError("PARSER_PIN_REQUIRED", "parser_name and parser_version are required")
    fetched_at = _text(payload.get("fetched_at")) or _now()
    try:
        manifest = build_source_version_manifest(
            source,
            content_hash=content_hash,
            byte_size=byte_size,
            fetched_at=fetched_at,
            parser_name=parser_name,
            parser_version=parser_version,
            fetch_url=_text(payload.get("fetch_url")) or _text(source.get("canonical_url")),
            source_etag=_text(payload.get("source_etag")),
            source_last_modified=_text(payload.get("source_last_modified")),
            response_content_type=_text(payload.get("response_content_type")),
            http_status=payload.get("http_status"),
            raw_content_ref=_text(payload.get("raw_content_ref")),
            raw_content_storage=_text(payload.get("raw_content_storage")),
            verification_method=_text(payload.get("verification_method")),
            status=_text(payload.get("status")) or "fetched",
        )
    except SourceVersionManifestError as exc:
        raise SourceRegistryError(exc.code, exc.message, details=exc.details) from exc
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND content_hash = ? AND (record_type = 'source_version' OR "
            "(record_type = 'document_revision' AND legacy_source_version_id <> '')) "
            "ORDER BY CASE WHEN record_type = 'source_version' THEN 0 ELSE 1 END, "
            "revision_no DESC, created_at DESC, id DESC LIMIT 1",
            (tenant_id, _text(source.get("source_document_id")), content_hash),
        ).fetchone()
        if existing:
            result = _decode_revision(_row_dict(existing) or {}, source)
            result["deduplicated"] = True
            result["idempotency"] = {"decision": "replay_same_url_same_content", "replayed": True}
            return result
        row = conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision WHERE tenant_id = ? AND document_id = ?",
            (tenant_id, _text(source.get("source_document_id"))),
        ).fetchone()
        revision_no = max(1, int(row[0] or 1))
        revision_id = "v1rev-" + hashlib.sha256(f"{source_id}:{content_hash}:{parser_version}".encode("utf-8")).hexdigest()[:32]
        # Source collection is a hash-only boundary.  The body may be passed
        # through to the same-request publication continuation, but the
        # immutable source manifest itself never persists raw content.
        original_content = ""
        now = fetched_at
        metadata = copy.deepcopy(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
        source_version_no_row = conn.execute(
            "SELECT COUNT(*) + 1 FROM ai_document_revision "
            "WHERE tenant_id = ? AND document_id = ? AND record_type = 'source_version'",
            (tenant_id, _text(source.get("source_document_id"))),
        ).fetchone()
        metadata["source_version_no"] = max(1, int(source_version_no_row[0] or 1))
        metadata["source_manifest"] = manifest
        revision = {
            "id": revision_id,
            "tenant_id": tenant_id,
            "document_id": _text(source.get("source_document_id")),
            "revision_no": revision_no,
            "canonical_url": _text(source.get("canonical_url")),
            "source_kind": _text(source.get("source_kind")),
            "fetch_url": _text(payload.get("fetch_url")) or _text(source.get("canonical_url")),
            "content_hash": content_hash,
            "normalized_content_hash": content_hash,
            "original_content": original_content,
            "normalized_content": "",
            "metadata_json": _db_json(metadata),
            "source_metadata_json": _db_json(source.get("metadata") or {}),
            "fetch_metadata_json": _db_json({"verification_method": _text(payload.get("verification_method")), "redirect_chain": metadata.get("redirect_chain", []), "resolved_addresses": metadata.get("resolved_addresses", [])}),
            "parser_name": parser_name,
            "parser_version": parser_version,
            "cleaner_name": "",
            "cleaner_version": "",
            "mime_type": _text(payload.get("response_content_type")),
            "byte_size": byte_size,
            "source_etag": _text(payload.get("source_etag")),
            "source_last_modified": _text(payload.get("source_last_modified")),
            "http_status": payload.get("http_status"),
            "fetched_at": now,
            "status": _text(payload.get("status")) or "fetched",
            "lifecycle_status": "published",
            "lifecycle_reason": "",
            "is_current": True if _database._USE_PG else 1,
            "legacy_source_id": _text(source.get("id")),
            "legacy_source_version_id": "",
            "legacy_document_id": "",
            "legacy_document_version_id": "",
            "created_at": now,
            "created_by": _actor(user),
            "record_type": "source_version",
            "observation_outcome": "",
            "detection_type": "none",
            "error_code": _text(payload.get("error_code")),
            "replacement_url": "",
            "request_method": "GET",
            "checked_at": None,
            "source_observation_id": "",
            "legacy_action_id": "",
        }
        conn.execute(
            "UPDATE ai_document_revision SET is_current = ? WHERE tenant_id = ? AND document_id = ? AND record_type = 'source_version'",
            (False if _database._USE_PG else 0, tenant_id, _text(source.get("source_document_id"))),
        )
        conn.execute(
            f"INSERT INTO ai_document_revision ({', '.join(revision)}) VALUES ({', '.join('?' for _ in revision)})",
            tuple(revision.values()),
        )
        metadata_source = copy.deepcopy(source.get("metadata") or {})
        metadata_source["last_version_id"] = revision_id
        conn.execute(
            "UPDATE ai_document SET source_content_hash = ?, source_fetched_at = ?, source_etag = ?, source_last_modified = ?, source_http_status = ?, source_byte_size = ?, source_parser_name = ?, source_parser_version = ?, source_raw_content_ref = ?, metadata_json = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            (content_hash, now, _text(payload.get("source_etag")), _text(payload.get("source_last_modified")), payload.get("http_status"), byte_size, parser_name, parser_version, _text(payload.get("raw_content_ref")), _db_json(metadata_source), _now(), tenant_id, _text(source.get("source_document_id"))),
        )
        conn.commit()
        result = _decode_revision(revision, source)
        result["deduplicated"] = False
        result["idempotency"] = {"decision": "new_version", "replayed": False}
        return result
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_source_versions(source_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    source = get_source(source_id, user)
    conn = get_db_connection()
    try:
        return [_decode_revision(row, source) for row in _source_revision_rows(conn, source)]
    finally:
        conn.close()


def _decode_document_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return the stable document shape used by the knowledge APIs."""
    result = dict(row)
    result["metadata"] = _json_load(result.pop("metadata_json", None), {})
    result["acl"] = _json_load(result.pop("acl_json", None), {})
    result.setdefault("document_id", result.get("id"))
    result.setdefault("lifecycle_status", result.get("status") or "draft")
    return result


def _find_compatible_merge_candidate(
    conn,
    *,
    tenant_id: str,
    source_document_id: str,
    content_hash: str,
    parser_name: str,
    parser_version: str,
    document_kind: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find an existing V1 document fact that may represent the same bytes."""

    rows = conn.execute(
        "SELECT r.*, d.id AS owner_id, d.status AS owner_status, "
        "d.lifecycle_status AS owner_lifecycle, d.knowledge_source_type "
        "FROM ai_document_revision r JOIN ai_document d "
        "ON d.tenant_id = r.tenant_id AND d.id = r.document_id "
        "WHERE r.tenant_id = ? AND r.record_type = 'document_revision' "
        "AND r.document_id <> ? AND r.content_hash = ? "
        "ORDER BY r.created_at ASC, r.id ASC",
        (tenant_id, source_document_id, content_hash),
    ).fetchall()
    for raw_row in rows:
        row = _row_dict(raw_row) or {}
        owner_state = _text(row.get("owner_lifecycle") or row.get("owner_status")).lower()
        version_state = _text(row.get("lifecycle_status") or row.get("status")).lower()
        if owner_state in {"disabled", "quarantined", "deleted", "purged"} or version_state in {"disabled", "quarantined", "deleted", "purged"}:
            continue
        if _text(row.get("parser_name")) != parser_name or _text(row.get("parser_version")) != parser_version:
            continue
        row_metadata = _json_load(row.get("metadata_json"), {})
        if not isinstance(row_metadata, dict) or _text(row_metadata.get("document_kind")) != document_kind:
            continue
        owner = {
            "id": _text(row.get("owner_id")),
            "tenant_id": tenant_id,
            "status": _text(row.get("owner_status")),
            "lifecycle_status": _text(row.get("owner_lifecycle")),
            "knowledge_source_type": _text(row.get("knowledge_source_type")),
        }
        return owner, row
    return None


def _record_document_source_link(
    conn,
    *,
    tenant_id: str,
    document: dict[str, Any],
    version: dict[str, Any],
    source: dict[str, Any],
    source_version: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    """Record a source-to-document merge fact in the V1 revision stream."""

    source_id = _text(source.get("id"))
    source_version_id = _text(source_version.get("id"))
    existing = _row_dict(conn.execute(
        "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
        "AND record_type = 'document_source_link' AND legacy_source_id = ? "
        "AND legacy_source_version_id = ? LIMIT 1",
        (tenant_id, _text(document.get("id")), source_id, source_version_id),
    ).fetchone())
    if existing:
        link_metadata = _json_load(existing.get("metadata_json"), {})
        if not isinstance(link_metadata, dict):
            link_metadata = {}
        link_metadata["observation_count"] = int(link_metadata.get("observation_count") or 0) + 1
        conn.execute(
            "UPDATE ai_document_revision SET metadata_json = ?, checked_at = ?, created_by = ? "
            "WHERE tenant_id = ? AND id = ?",
            (_db_json(link_metadata), _now(), _actor(user), tenant_id, _text(existing.get("id"))),
        )
        updated = _row_dict(conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND id = ?",
            (tenant_id, _text(existing.get("id"))),
        ).fetchone()) or existing
        return updated

    next_row = conn.execute(
        "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision "
        "WHERE tenant_id = ? AND document_id = ?",
        (tenant_id, _text(document.get("id"))),
    ).fetchone()
    now = _now()
    link_metadata = {
        "canonical_url": _text(source.get("canonical_url")),
        "content_hash": _text(version.get("content_hash")),
        "document_version_id": _text(version.get("id")),
        "observation_count": 1,
    }
    values = {
        "id": "v1link-" + hashlib.sha256(f"{tenant_id}:{document.get('id')}:{source_id}:{source_version_id}".encode("utf-8")).hexdigest()[:32],
        "tenant_id": tenant_id,
        "document_id": _text(document.get("id")),
        "revision_no": max(1, int(next_row[0] or 1)),
        "canonical_url": _text(source.get("canonical_url")),
        "source_kind": _text(source.get("source_kind")),
        "fetch_url": _text(source_version.get("fetch_url")),
        # Keep the unique content-hash index reserved for actual document
        # revisions; the link's immutable content hash lives in metadata.
        "content_hash": "",
        "normalized_content_hash": "",
        "original_content": "",
        "normalized_content": "",
        "metadata_json": _db_json(link_metadata),
        "source_metadata_json": _db_json(source.get("metadata") or {}),
        "fetch_metadata_json": _db_json({}),
        "parser_name": _text(source_version.get("parser_name")),
        "parser_version": _text(source_version.get("parser_version")),
        "cleaner_name": "",
        "cleaner_version": "",
        "mime_type": _text(source_version.get("response_content_type")),
        "byte_size": int(source_version.get("byte_size") or 0),
        "source_etag": _text(source_version.get("source_etag")),
        "source_last_modified": _text(source_version.get("source_last_modified")),
        "http_status": source_version.get("http_status"),
        "fetched_at": source_version.get("fetched_at") or now,
        "status": "observed",
        "lifecycle_status": "observed",
        "lifecycle_reason": "same-content-source-merge",
        "is_current": False if _database._USE_PG else 0,
        "legacy_source_id": source_id,
        "legacy_source_version_id": source_version_id,
        "legacy_document_id": _text(source.get("source_document_id")),
        "legacy_document_version_id": _text(version.get("id")),
        "created_at": now,
        "created_by": _actor(user),
        "record_type": "document_source_link",
        "observation_outcome": "merged",
        "detection_type": "none",
        "error_code": "",
        "replacement_url": "",
        "request_method": "GET",
        "checked_at": now,
        "source_observation_id": "",
        "legacy_action_id": "",
    }
    names = list(values)
    conn.execute(
        f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(values[name] for name in names),
    )
    return values


def record_document_revision(
    document_id: str,
    source: dict[str, Any],
    source_version: dict[str, Any],
    user: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    original_content: str | bytes | None = None,
    normalized_content: str | None = None,
    cleaner_name: str = "",
    cleaner_version: str = "",
    document_kind: str = "official_manual",
) -> dict[str, Any]:
    """Attach one fetched source fact to a V1 document revision.

    The source-version payload is already an immutable V1 revision produced by
    :func:`record_source_version`.  This function only adds the searchable
    normalized representation and links it to the actual ``ai_document`` that
    owns the chunks.  It never creates or updates a legacy document table.
    """
    source_id = _text(source.get("id"))
    if not source_id:
        raise SourceRegistryError("SOURCE_REQUIRED", "A source is required", status_code=400)
    resolved_source = get_source(source_id, user)
    tenant_id = _text(resolved_source.get("tenant_id"))
    supplied_source_url = _text(source.get("canonical_url") or source.get("source"))
    authoritative_source_url = _text(resolved_source.get("canonical_url") or resolved_source.get("source"))
    if supplied_source_url and supplied_source_url != authoritative_source_url:
        raise SourceRegistryError("DOCUMENT_SOURCE_FACT_MISMATCH", "document source URL does not match the registered source", status_code=409)
    supplied_source_kind = _text(source.get("source_kind"))
    authoritative_source_kind = _text(resolved_source.get("source_kind"))
    if supplied_source_kind and authoritative_source_kind and supplied_source_kind != authoritative_source_kind:
        raise SourceRegistryError("DOCUMENT_SOURCE_FACT_MISMATCH", "document source kind does not match the registered source", status_code=409)
    target_id = _text(document_id)
    if not target_id:
        raise SourceRegistryError("DOCUMENT_REQUIRED", "A document is required", status_code=400)
    source_document_id = _text(resolved_source.get("source_document_id") or resolved_source.get("id"))
    is_source_identity = target_id == source_document_id
    raw = original_content
    if isinstance(raw, bytes):
        try:
            original_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceRegistryError("DOCUMENT_CONTENT_INVALID", "original_content must be UTF-8") from exc
    elif raw is None:
        original_text = _text(source_version.get("original_content"))
    else:
        original_text = str(raw)
    normalized_text = str(normalized_content if normalized_content is not None else source_version.get("normalized_content") or "")
    source_hash = _text(source_version.get("content_hash")).lower()
    if not source_hash and original_text:
        source_hash = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
    if not _SHA256_RE.fullmatch(source_hash):
        raise SourceRegistryError("INVALID_CONTENT_HASH", "source version content_hash is invalid")
    if original_content is not None and hashlib.sha256(original_text.encode("utf-8")).hexdigest() != source_hash:
        raise SourceRegistryError("DOCUMENT_HASH_MISMATCH", "original_content does not match source content hash", status_code=409)
    if original_content is not None and int(source_version.get("byte_size") or 0) != len(original_text.encode("utf-8")):
        raise SourceRegistryError("DOCUMENT_BYTE_SIZE_MISMATCH", "original_content does not match source byte_size", status_code=409)
    normalized_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() if normalized_text else ""
    supplied_metadata = metadata if isinstance(metadata, dict) else {}
    source_metadata = resolved_source.get("metadata") if isinstance(resolved_source.get("metadata"), dict) else {}
    merged_metadata = copy.deepcopy(source_metadata)
    merged_metadata.update(copy.deepcopy(supplied_metadata))
    merged_metadata["source_registry_id"] = source_id
    merged_metadata["source_version_id"] = _text(source_version.get("id"))
    merged_metadata.setdefault("document_kind", _text(document_kind) or "official_manual")
    now = _now()
    conn = get_db_connection()
    try:
        target = _row_dict(conn.execute(
            "SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?",
            (tenant_id, target_id),
        ).fetchone())
        if not target:
            raise SourceRegistryError("DOCUMENT_NOT_FOUND", "Document was not found", status_code=404)
        source_version_id = _text(source_version.get("id") or source_version.get("source_version_id"))
        authoritative_version = None
        if source_version_id:
            authoritative_version = _row_dict(conn.execute(
                "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? AND id = ? LIMIT 1",
                (tenant_id, source_document_id, source_version_id),
            ).fetchone())
            if not authoritative_version:
                raise SourceRegistryError("DOCUMENT_SOURCE_FACT_MISMATCH", "document source version is not registered", status_code=409)
            authoritative_hash = _text(authoritative_version.get("content_hash"))
            if source_hash != authoritative_hash:
                raise SourceRegistryError("DOCUMENT_SOURCE_FACT_MISMATCH", "document source version hash does not match the registered fact", status_code=409)
            if source_version.get("byte_size") is not None and int(source_version.get("byte_size") or 0) != int(authoritative_version.get("byte_size") or 0):
                raise SourceRegistryError("DOCUMENT_SOURCE_FACT_MISMATCH", "document source version size does not match the registered fact", status_code=409)
        merge_candidate = None
        if is_source_identity:
            merge_candidate = _find_compatible_merge_candidate(
                conn,
                tenant_id=tenant_id,
                source_document_id=source_document_id,
                content_hash=source_hash,
                parser_name=_text(source_version.get("parser_name")),
                parser_version=_text(source_version.get("parser_version")),
                document_kind=_text(document_kind) or "official_manual",
            )
        if merge_candidate:
            candidate_document, candidate_version = merge_candidate
            candidate_row = _row_dict(conn.execute(
                "SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?",
                (tenant_id, _text(candidate_document.get("id"))),
            ).fetchone()) or candidate_document
            link = _record_document_source_link(
                conn,
                tenant_id=tenant_id,
                document=candidate_row,
                version=candidate_version,
                source=resolved_source,
                source_version=source_version,
                user=user,
            )
            conn.execute(
                "UPDATE ai_document SET lifecycle_status = 'draft', lifecycle_reason = ?, "
                "lifecycle_changed_at = ?, lifecycle_changed_by = ?, updated_at = ? "
                "WHERE tenant_id = ? AND id = ?",
                ("awaiting_publication", now, _actor(user), now, tenant_id, source_document_id),
            )
            conn.commit()
            decoded_document = _decode_document_row(candidate_row)
            decoded_version = _decode_revision(candidate_version, resolved_source)
            decoded_version["document_kind"] = _text(document_kind) or "official_manual"
            return {
                "decision": "merge_same_content_different_source",
                "replayed": True,
                "merged": True,
                "changed": False,
                "document": decoded_document,
                "document_version": decoded_version,
                "source_observation": _decode_observation(link),
            }
        existing = _row_dict(conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'document_revision' AND content_hash = ? LIMIT 1",
            (tenant_id, target_id, source_hash),
        ).fetchone())
        source_link = None
        if existing:
            revision_id = _text(existing.get("id"))
            existing_lifecycle = "draft" if is_source_identity else (_text(existing.get("lifecycle_status")) or "published")
            existing_status = "draft" if is_source_identity else (_text(existing.get("status")) or "published")
            conn.execute(
                "UPDATE ai_document_revision SET normalized_content = ?, normalized_content_hash = ?, "
                "original_content = CASE WHEN ? <> '' THEN ? ELSE original_content END, "
                "metadata_json = ?, cleaner_name = ?, cleaner_version = ?, lifecycle_status = ?, "
                "status = ?, is_current = ?, created_by = COALESCE(NULLIF(created_by, ''), ?), "
                "fetched_at = COALESCE(fetched_at, ?), source_kind = COALESCE(NULLIF(source_kind, ''), ?) "
                "WHERE tenant_id = ? AND id = ?",
                (
                    normalized_text, normalized_hash, original_text, original_text,
                    _db_json(merged_metadata), _text(cleaner_name), _text(cleaner_version),
                    existing_lifecycle, existing_status,
                    True if _database._USE_PG else 1, _actor(user),
                    source_version.get("fetched_at") or now, _text(resolved_source.get("source_kind")),
                    tenant_id, revision_id,
                ),
            )
            revision = _row_dict(conn.execute(
                "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND id = ?",
                (tenant_id, revision_id),
            ).fetchone()) or existing
            decision = "replay_same_document_content"
            replayed = True
            source_link = _record_document_source_link(
                conn,
                tenant_id=tenant_id,
                document=target,
                version=revision,
                source=resolved_source,
                source_version=source_version,
                user=user,
            )
        else:
            previous_row = conn.execute(
                "SELECT id FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
                "AND record_type = 'document_revision' AND is_current = ? "
                "ORDER BY revision_no DESC, created_at DESC, id DESC LIMIT 1",
                (tenant_id, target_id, True if _database._USE_PG else 1),
            ).fetchone()
            previous_id = _text(previous_row[0]) if previous_row else ""
            conn.execute(
                "UPDATE ai_document_revision SET is_current = ? WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision'",
                (False if _database._USE_PG else 0, tenant_id, target_id),
            )
            row = conn.execute(
                "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision "
                "WHERE tenant_id = ? AND document_id = ?",
                (tenant_id, target_id),
            ).fetchone()
            revision_no = max(1, int(row[0] or 1))
            revision_id = "v1docrev-" + hashlib.sha256(f"{target_id}:{source_hash}:{revision_no}".encode("utf-8")).hexdigest()[:32]
            document_version_row = conn.execute(
                "SELECT COUNT(*) + 1 FROM ai_document_revision "
                "WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision'",
                (tenant_id, target_id),
            ).fetchone()
            merged_metadata["document_version_no"] = max(1, int(document_version_row[0] or 1))
            if previous_id:
                merged_metadata["supersedes_version_id"] = previous_id
            fetch_metadata = {
                "verification_method": _text(source_version.get("verification_method")),
                "source_version_id": _text(source_version.get("id")),
                "redirect_chain": (source_version.get("metadata") or {}).get("redirect_chain", []) if isinstance(source_version.get("metadata"), dict) else [],
            }
            revision_values = {
                "id": revision_id,
                "tenant_id": tenant_id,
                "document_id": target_id,
                "revision_no": revision_no,
                "canonical_url": _text(resolved_source.get("canonical_url")),
                "source_kind": _text(resolved_source.get("source_kind")),
                "fetch_url": _text(source_version.get("fetch_url")) or _text(resolved_source.get("canonical_url")),
                "content_hash": source_hash,
                "normalized_content_hash": normalized_hash,
                "original_content": original_text,
                "normalized_content": normalized_text,
                "metadata_json": _db_json(merged_metadata),
                "source_metadata_json": _db_json(source_metadata),
                "fetch_metadata_json": _db_json(fetch_metadata),
                "parser_name": _text(source_version.get("parser_name")),
                "parser_version": _text(source_version.get("parser_version")),
                "cleaner_name": _text(cleaner_name),
                "cleaner_version": _text(cleaner_version),
                "mime_type": _text(source_version.get("response_content_type")),
                "byte_size": max(0, int(source_version.get("byte_size") or len(original_text.encode("utf-8")))),
                "source_etag": _text(source_version.get("source_etag")),
                "source_last_modified": _text(source_version.get("source_last_modified")),
                "http_status": source_version.get("http_status"),
                "fetched_at": source_version.get("fetched_at") or now,
                "status": "draft" if is_source_identity else "published",
                "lifecycle_status": "draft" if is_source_identity else "published",
                "lifecycle_reason": "",
                "is_current": True if _database._USE_PG else 1,
                "legacy_source_id": source_id,
                "legacy_source_version_id": _text(source_version.get("id")),
                "legacy_document_id": target_id,
                "legacy_document_version_id": "",
                "created_at": now,
                "created_by": _actor(user),
                "record_type": "document_revision",
                "observation_outcome": "",
                "detection_type": "none",
                "error_code": "",
                "replacement_url": "",
                "request_method": "GET",
                "checked_at": None,
                "source_observation_id": "",
                "legacy_action_id": "",
            }
            names = list(revision_values)
            conn.execute(
                f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                tuple(revision_values[name] for name in names),
            )
            revision = revision_values
            decision = "new_version"
            replayed = False
            source_link = _record_document_source_link(
                conn,
                tenant_id=tenant_id,
                document=target,
                version=revision_values,
                source=resolved_source,
                source_version=source_version,
                user=user,
            )
        document_metadata = _json_load(target.get("metadata_json"), {})
        if not isinstance(document_metadata, dict):
            document_metadata = {}
        document_metadata.update(merged_metadata)
        columns = _table_columns(conn, "ai_document")
        fields: dict[str, Any] = {
            "normalized_content": normalized_text,
            "original_content": original_text,
            "content_hash": normalized_hash or source_hash,
            "source_content_hash": source_hash,
            "source_fetched_at": source_version.get("fetched_at") or now,
            "source_etag": _text(source_version.get("source_etag")),
            "source_last_modified": _text(source_version.get("source_last_modified")),
            "source_http_status": source_version.get("http_status"),
            "source_byte_size": max(0, int(source_version.get("byte_size") or len(original_text.encode("utf-8")))),
            "source_parser_name": _text(source_version.get("parser_name")),
            "source_parser_version": _text(source_version.get("parser_version")),
            "metadata_json": _db_json(document_metadata),
            "ingestion_status": "ready" if normalized_text else "source_only",
            "current_version_id": revision_id,
            "updated_at": now,
        }
        if is_source_identity:
            # The source row is also the V1 document identity, but a fetched
            # source is not publish approval.  Keep the source collectable
            # (status=active) while leaving its revision in draft until the
            # explicit publication/lifecycle boundary is crossed.
            fields.update(
                {
                    "status": _text(target.get("status")) or "active",
                    "lifecycle_status": "draft",
                    "lifecycle_revision": int(target.get("lifecycle_revision") or 0) + 1,
                    "lifecycle_changed_at": now,
                    "lifecycle_changed_by": _actor(user),
                    "lifecycle_reason": "awaiting_publication",
                }
            )
        filtered = {key: value for key, value in fields.items() if key in columns}
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        conn.execute(
            f"UPDATE ai_document SET {assignments} WHERE tenant_id = ? AND id = ?",
            tuple(filtered.values()) + (tenant_id, target_id),
        )
        conn.commit()
        document = _row_dict(conn.execute(
            "SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, target_id)
        ).fetchone()) or target
        decoded_document = _decode_document_row(document)
        decoded_version = _decode_revision(revision, resolved_source)
        decoded_version.update({"document_kind": _text(document_kind) or "official_manual"})
        return {
            "decision": decision,
            "replayed": replayed,
            "merged": False,
            "changed": not replayed,
            "document": decoded_document,
            "document_version": decoded_version,
            "source_observation": _decode_observation(source_link) if source_link else None,
        }
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    """V1-compatible adapter for the former document-version API."""
    del collection_id
    target_id = _text(source.get("source_document_id") or source.get("id"))
    return record_document_revision(
        target_id,
        source,
        source_version,
        user,
        metadata=metadata,
        original_content=original_content,
        normalized_content=normalized_content,
        document_kind=document_kind,
    )


def record_source_refresh_observation(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    tenant_id = _text(source.get("tenant_id"))
    _authorize(user, "create", tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision WHERE tenant_id = ? AND document_id = ?",
            (tenant_id, _text(source.get("source_document_id"))),
        ).fetchone()
        observation_id = "v1obs-" + uuid.uuid4().hex
        # Keep enough precision for bounded refresh batches: several source
        # observations can be written in the same second, and the API orders
        # them by checked_at before the UUID tie-breaker.
        now = _text(payload.get("checked_at")) or datetime.now(timezone.utc).isoformat()
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        signal = payload.get("version_signal") if isinstance(payload.get("version_signal"), dict) else {}
        observation = {
            "id": observation_id,
            "tenant_id": tenant_id,
            "document_id": _text(source.get("source_document_id")),
            "revision_no": max(1, int(row[0] or 1)),
            "canonical_url": _text(source.get("canonical_url")),
            "source_kind": _text(source.get("source_kind")),
            "fetch_url": _text(payload.get("fetch_url")) or _text(source.get("canonical_url")),
            "content_hash": _text(payload.get("content_hash")),
            "normalized_content_hash": "",
            "original_content": "",
            "normalized_content": "",
            "metadata_json": _db_json(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
            "source_metadata_json": _db_json(source.get("metadata") or {}),
            "fetch_metadata_json": _db_json({"error": error, "version_signal": signal}),
            "parser_name": "",
            "parser_version": "",
            "cleaner_name": "",
            "cleaner_version": "",
            "mime_type": _text(payload.get("response_content_type")),
            "byte_size": max(0, int(payload.get("byte_size") or 0)),
            "source_etag": _text(payload.get("source_etag")),
            "source_last_modified": _text(payload.get("source_last_modified")),
            "http_status": payload.get("http_status"),
            "fetched_at": now,
            "status": "observed",
            "lifecycle_status": "observed",
            "lifecycle_reason": "",
            "is_current": False if _database._USE_PG else 0,
            "legacy_source_id": _text(source.get("id")),
            "legacy_source_version_id": _text(payload.get("source_version_id")),
            "legacy_document_id": "",
            "legacy_document_version_id": "",
            "created_at": now,
            "created_by": _actor(user),
            "record_type": "source_observation",
            "observation_outcome": _text(payload.get("outcome")) or "failed",
            "detection_type": _text(payload.get("detection_type")) or "none",
            "error_code": _text(payload.get("error_code")),
            "replacement_url": _text(payload.get("replacement_url")),
            "request_method": _text(payload.get("request_method")) or "GET",
            "checked_at": now,
            "source_observation_id": "",
            "legacy_action_id": "",
        }
        conn.execute(
            f"INSERT INTO ai_document_revision ({', '.join(observation)}) VALUES ({', '.join('?' for _ in observation)})",
            tuple(observation.values()),
        )
        conn.commit()
        return _decode_observation(observation)
    finally:
        conn.close()


def _decode_observation(row: dict[str, Any]) -> dict[str, Any]:
    fetch = _json_load(row.get("fetch_metadata_json"), {})
    if not isinstance(fetch, dict):
        fetch = {}
    metadata = _json_load(row.get("metadata_json"), {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": _text(row.get("id")),
        "tenant_id": _text(row.get("tenant_id")),
        "source_registry_id": _text(row.get("legacy_source_id")),
        "source_version_id": _text(row.get("legacy_source_version_id")),
        "checked_at": row.get("checked_at") or row.get("fetched_at"),
        "request_method": _text(row.get("request_method")) or "GET",
        "http_status": row.get("http_status"),
        "outcome": _text(row.get("observation_outcome")),
        "content_hash": _text(row.get("content_hash")),
        "byte_size": int(row.get("byte_size") or 0),
        "source_etag": _text(row.get("source_etag")),
        "source_last_modified": _text(row.get("source_last_modified")),
        "fetch_url": _text(row.get("fetch_url")),
        "response_content_type": _text(row.get("mime_type")),
        "error_code": _text(row.get("error_code")),
        "error": fetch.get("error") if isinstance(fetch.get("error"), dict) else {},
        "metadata": metadata,
        "observation_count": int(metadata.get("observation_count") or 1),
        "detection_type": _text(row.get("detection_type")) or "none",
        "replacement_url": _text(row.get("replacement_url")),
        "version_signal": fetch.get("version_signal") if isinstance(fetch.get("version_signal"), dict) else {},
        "created_at": row.get("created_at"),
    }


def record_site_alert(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Append a bounded site-alert fact to the V1 provenance stream."""
    source = get_source(source_id, user)
    tenant_id = _text(source.get("tenant_id"))
    _authorize(user, "create", tenant_id)
    alert = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    alert["host"] = _text(alert.get("host"))[:255].lower()
    alert["alert_code"] = _text(alert.get("alert_code"))[:128]
    alert["severity"] = _text(alert.get("severity") or "warning")[:16]
    alert["title"] = _text(alert.get("title") or "Official source site anomaly")[:256]
    alert["status"] = _text(alert.get("status") or "open")[:16]
    alert["source_ids"] = sorted({_text(item)[:128] for item in (alert.get("source_ids") or []) if _text(item)})
    if not alert["host"] or not alert["alert_code"]:
        raise SourceRegistryError("SITE_ALERT_INVALID", "Site alert host and alert_code are required")
    now = _text(alert.get("last_seen_at")) or datetime.now(timezone.utc).isoformat()
    alert.setdefault("first_seen_at", now)
    alert.setdefault("last_seen_at", now)
    alert.setdefault("failure_count", max(1, int(alert.get("observed_count") or 1)))
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision WHERE tenant_id = ? AND document_id = ?",
            (tenant_id, _text(source.get("source_document_id") or source.get("id"))),
        ).fetchone()
        values = {
            "id": "v1alert-" + uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "document_id": _text(source.get("source_document_id") or source.get("id")),
            "revision_no": max(1, int(row[0] or 1)),
            "canonical_url": _text(source.get("canonical_url")),
            "source_kind": _text(source.get("source_kind")),
            "fetch_url": _text(source.get("canonical_url")),
            "content_hash": "",
            "normalized_content_hash": "",
            "original_content": "",
            "normalized_content": "",
            "metadata_json": _db_json({"site_alert": alert}),
            "source_metadata_json": _db_json(source.get("metadata") or {}),
            "fetch_metadata_json": _db_json({}),
            "parser_name": "",
            "parser_version": "",
            "cleaner_name": "",
            "cleaner_version": "",
            "mime_type": "",
            "byte_size": 0,
            "source_etag": "",
            "source_last_modified": "",
            "http_status": None,
            "fetched_at": now,
            "status": "observed",
            "lifecycle_status": "observed",
            "lifecycle_reason": "",
            "is_current": False if _database._USE_PG else 0,
            "legacy_source_id": _text(source.get("id")),
            "legacy_source_version_id": "",
            "legacy_document_id": "",
            "legacy_document_version_id": "",
            "created_at": now,
            "created_by": _actor(user),
            "record_type": "site_alert",
            "observation_outcome": "failed",
            "detection_type": "none",
            "error_code": _text(alert.get("alert_code")),
            "replacement_url": "",
            "request_method": "GET",
            "checked_at": now,
            "source_observation_id": "",
            "legacy_action_id": "",
        }
        names = list(values)
        conn.execute(
            f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            tuple(values[name] for name in names),
        )
        conn.commit()
        return {"id": values["id"], "source_id": _text(source.get("id")), **alert}
    finally:
        conn.close()


def list_source_refresh_observations(source_id: str, user: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    source = get_source(source_id, user)
    bounded = max(1, min(200, int(limit)))
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? AND record_type = 'source_observation' ORDER BY checked_at DESC, id DESC LIMIT ?",
            (_text(source.get("tenant_id")), _text(source.get("source_document_id")), bounded),
        ).fetchall()
        return [_decode_observation(_row_dict(row) or {}) for row in rows]
    finally:
        conn.close()


def get_source_refresh_status(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
    source = get_source(source_id, user)
    observations = list_source_refresh_observations(source_id, user, limit=200)
    versions = list_source_versions(source_id, user)
    latest = observations[0] if observations else {}
    counts = {key: 0 for key in ("not_modified", "unchanged", "changed", "failed", "removed", "replacement", "version_updated")}
    for item in observations:
        for key in (str(item.get("outcome") or ""), str(item.get("detection_type") or "none")):
            if key in counts:
                counts[key] += 1
    if not observations:
        freshness = "never_checked"
    elif str(latest.get("outcome") or "") == "failed":
        freshness = "failed"
    elif str(latest.get("detection_type") or "none") in {"removed", "replacement"}:
        freshness = "attention"
    else:
        freshness = "healthy"
    latest_version = versions[0] if versions else None
    return {
        "source_id": _text(source.get("id")),
        "tenant_id": _text(source.get("tenant_id")),
        "registry_status": _text(source.get("status")),
        "validation_status": _text(source.get("validation_status")) or "unvalidated",
        "fetch_enabled": bool(source.get("fetch_enabled")),
        "freshness_status": freshness,
        "last_checked_at": latest.get("checked_at"),
        "last_outcome": latest.get("outcome"),
        "last_detection_type": latest.get("detection_type") or "none",
        "last_error_code": _text(latest.get("error_code"))[:128],
        "last_content_hash": _text(latest.get("content_hash"))[:64],
        "last_source_version_id": _text(latest.get("source_version_id")),
        "last_http_status": latest.get("http_status"),
        "observation_count": len(observations),
        "counts": counts,
        "latest_version": {
            "id": _text(latest_version.get("id")),
            "content_hash": _text(latest_version.get("content_hash")),
            "byte_size": int(latest_version.get("byte_size") or 0),
            "fetched_at": latest_version.get("fetched_at"),
            "status": latest_version.get("status"),
        } if latest_version else None,
    }


def _is_material_replacement(source: dict[str, Any], final_url: str) -> bool:
    try:
        original = _canonicalize_url(source.get("canonical_url"))[0]
        redirected = _canonicalize_url(final_url)[0]
    except SourceRegistryError:
        return True
    original_parts = urlsplit(original)
    redirected_parts = urlsplit(redirected)
    if original_parts.hostname != redirected_parts.hostname:
        return True
    original_path = original_parts.path.rstrip("/") or "/"
    redirected_path = redirected_parts.path.rstrip("/") or "/"
    if original_path == redirected_path:
        return False
    return redirected_path not in {original_path + "/index.html", original_path + "/index.htm"}


def _apply_change_detection(
    source_id: str,
    user: dict[str, Any],
    *,
    detection_type: str,
    observation: dict[str, Any],
    reason_code: str,
    replacement_url: str = "",
    source_version_id: str = "",
) -> dict[str, Any]:
    """Apply a destructive source signal while keeping refresh resilient."""
    from services.official_source_change_service import apply_official_source_detection

    try:
        return apply_official_source_detection(
            source_id,
            user,
            detection_type=detection_type,
            reason_code=reason_code,
            replacement_url=replacement_url,
            source_version_id=source_version_id,
            refresh_observation_id=str(observation.get("id") or ""),
        )
    except SourceRegistryError as exc:
        return {
            "source_id": source_id,
            "applied": False,
            "detection_type": detection_type,
            "action_id": "v1change-" + str(observation.get("id") or ""),
            "action_status": "failed",
            "error_code": str(exc.code or "SOURCE_CHANGE_APPLY_FAILED")[:128],
            "documents_quarantined": 0,
            "document_errors": [],
        }


def collect_source(
    source_id: str,
    request: dict[str, Any] | None,
    user: dict[str, Any],
    *,
    transport: Any = None,
    resolver: Any = None,
    client_factory: Callable[..., Any] | None = None,
    operational_policy: Any = None,
    backoff_base_seconds: float = 0.0,
    sleeper: Callable[[float], None] | None = None,
    content_sink: Callable[[bytes, str], None] | None = None,
) -> dict[str, Any]:
    from services.safe_outbound_http import OutboundCollectionError, check_robots_policy, safe_fetch

    source = get_source(source_id, user)
    method = _text((request or {}).get("method") or "GET").upper()
    latest = (list_source_versions(source_id, user) or [None])[0]
    policy = source.get("collection_policy") if isinstance(source.get("collection_policy"), dict) else copy.deepcopy(_DEFAULT_COLLECTION_POLICY)
    source_for_fetch = dict(source)
    source_for_fetch["collection_policy"] = policy
    if operational_policy:
        robots = check_robots_policy(source_for_fetch, transport=transport, resolver=resolver, client_factory=client_factory, backoff_base_seconds=backoff_base_seconds, sleeper=sleeper or time.sleep)
    else:
        robots = {
            "policy": "not_checked",
            "outcome": "not_checked",
            "allowed": True,
            "error_code": "",
            "status_code": None,
            "bytes_read": 0,
            "review_required": False,
        }
    if not robots.get("allowed"):
        code = _text(robots.get("error_code")) or "ROBOTS_POLICY_DENIED"
        observation = record_source_refresh_observation(source_id, {"request_method": method, "outcome": "failed", "error_code": code, "error": {"code": code}, "metadata": {"robots": robots}}, user)
        raise SourceRegistryError(code, "Source collection was denied by the registered robots policy", status_code=403, details={"robots_outcome": _text(robots.get("outcome"))})
    _audit(
        event_type="fetch_started",
        user=user,
        source=source,
        details={"method": method, "robots_outcome": _text(robots.get("outcome"))},
    )
    try:
        result = safe_fetch(
            source_for_fetch,
            method=method,
            transport=transport,
            resolver=resolver,
            client_factory=client_factory,
            conditional_headers={
                "if-none-match": (latest or {}).get("source_etag") or "",
                "if-modified-since": (latest or {}).get("source_last_modified") or "",
            },
            backoff_base_seconds=backoff_base_seconds,
            sleeper=sleeper or time.sleep,
        )
    except OutboundCollectionError as exc:
        details = dict(exc.details or {}) if isinstance(exc.details, dict) else {}
        status_code = int(details.get("http_status") or 0)
        detection = "removed" if exc.code == "OUTBOUND_HTTP_SOURCE_NOT_FOUND" and status_code in {404, 410} and latest else "none"
        observation = record_source_refresh_observation(source_id, {"request_method": method, "http_status": status_code or None, "outcome": "failed", "source_version_id": (latest or {}).get("id") or "", "content_hash": (latest or {}).get("content_hash") or "", "byte_size": (latest or {}).get("byte_size") or 0, "error_code": "OFFICIAL_SOURCE_REMOVED" if detection == "removed" else exc.code, "error": {"code": "OFFICIAL_SOURCE_REMOVED" if detection == "removed" else exc.code}, "detection_type": detection, "version_signal": {"previous_content_hash": (latest or {}).get("content_hash") or "", "http_status": status_code}}, user)
        if detection == "removed":
            application = _apply_change_detection(
                source_id,
                user,
                detection_type="removed",
                observation=observation,
                reason_code=f"HTTP_{status_code}",
                source_version_id=str((latest or {}).get("id") or ""),
            )
            return {
                "source_id": source_id,
                "fetch": {"status_code": status_code, "not_modified": False, "bytes_read": 0},
                "version": None,
                "policy": {"robots": robots},
                "refresh": {
                    "outcome": "changed",
                    "collection_outcome": "failed",
                    "error_code": "OFFICIAL_SOURCE_REMOVED",
                    "content_hash": (latest or {}).get("content_hash") or "",
                    "source_version_id": (latest or {}).get("id") or "",
                    "observation_id": observation.get("id"),
                    "detection_type": "removed",
                    "change_application": application,
                },
            }
        raise SourceRegistryError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    fetch_metadata = result.as_dict(include_content=False)
    _audit(
        event_type="fetch_completed",
        user=user,
        source=source,
        details={
            "method": method,
            "status_code": result.status_code,
            "not_modified": bool(result.not_modified),
            "bytes_read": int(result.bytes_read or 0),
        },
    )
    if result.not_modified:
        observation = record_source_refresh_observation(source_id, {"request_method": method, "http_status": result.status_code, "outcome": "not_modified", "source_version_id": (latest or {}).get("id") or "", "content_hash": (latest or {}).get("content_hash") or "", "byte_size": (latest or {}).get("byte_size") or 0, "source_etag": result.source_etag or (latest or {}).get("source_etag") or "", "source_last_modified": result.source_last_modified or (latest or {}).get("source_last_modified") or "", "fetch_url": result.final_url, "response_content_type": result.content_type, "metadata": {"conditional_request": True}, "detection_type": "none", "version_signal": {"previous_content_hash": (latest or {}).get("content_hash") or "", "http_status": result.status_code}}, user)
        return {"source_id": source_id, "fetch": fetch_metadata, "version": None, "policy": {"robots": robots}, "refresh": {"outcome": "not_modified", "content_hash": (latest or {}).get("content_hash") or "", "source_version_id": (latest or {}).get("id") or "", "observation_id": observation.get("id"), "detection_type": "none", "change_application": None}}
    if method == "HEAD":
        return {"source_id": source_id, "fetch": fetch_metadata, "version": None, "policy": {"robots": robots}}
    if content_sink is not None:
        content_sink(result.content, result.content_type)
    version = record_source_version(source_id, {"content": result.content, "fetched_at": _now(), "parser_name": policy.get("parser_name"), "parser_version": policy.get("parser_version"), "source_etag": result.source_etag, "source_last_modified": result.source_last_modified, "fetch_url": result.final_url, "response_content_type": result.content_type, "http_status": result.status_code, "verification_method": "v1_safe_outbound_http", "metadata": {"redirect_chain": list(result.redirect_chain), "resolved_addresses": list(result.resolved_addresses), "bytes_read": result.bytes_read, "elapsed_ms": result.elapsed_ms}, "status": "fetched"}, user)
    outcome = "unchanged" if version.get("deduplicated") else "changed"
    detection = "replacement" if _is_material_replacement(source, result.final_url) else ("version_updated" if latest and outcome == "changed" and _text(source.get("source_kind")) in _OFFICIAL_KINDS else "none")
    observation = record_source_refresh_observation(source_id, {"request_method": method, "http_status": result.status_code, "outcome": outcome, "source_version_id": version.get("id") or "", "content_hash": version.get("content_hash") or "", "byte_size": version.get("byte_size") or result.bytes_read, "source_etag": result.source_etag, "source_last_modified": result.source_last_modified, "fetch_url": result.final_url, "response_content_type": result.content_type, "metadata": {"conditional_request": bool(latest), "deduplicated": bool(version.get("deduplicated"))}, "detection_type": detection, "replacement_url": result.final_url if detection == "replacement" else "", "version_signal": {"previous_content_hash": (latest or {}).get("content_hash") or "", "new_content_hash": version.get("content_hash") or "", "redirected": bool(result.redirect_chain)}}, user)
    application = None
    if detection == "replacement":
        application = _apply_change_detection(
            source_id,
            user,
            detection_type=detection,
            observation=observation,
            reason_code="OFFICIAL_SOURCE_REPLACED",
            replacement_url=result.final_url,
            source_version_id=str(version.get("id") or ""),
        )
    version["refresh_observation_id"] = observation.get("id")
    version["detection_type"] = detection
    return {"source_id": source_id, "fetch": fetch_metadata, "version": version, "policy": {"robots": robots}, "refresh": {"outcome": outcome, "content_hash": version.get("content_hash") or "", "source_version_id": version.get("id") or "", "observation_id": observation.get("id"), "detection_type": detection, "replacement_url": result.final_url if detection == "replacement" else "", "change_application": application}}


__all__ = [
    "SourceRegistryError", "REGISTRY_STATUSES", "VERSION_STATUSES", "SOURCE_TYPES", "SOURCE_KINDS", "TRUST_LEVELS",
    "validate_official_url_input", "create_source", "list_sources", "get_source", "update_source", "validate_source",
    "enable_source", "disable_source", "quarantine_source_for_change", "delete_source", "record_source_version",
    "list_source_versions", "record_source_refresh_observation", "list_source_refresh_observations", "get_source_refresh_status",
    "record_document_revision", "record_document_version", "record_site_alert", "collect_source", "_canonicalize_url", "_decode_registry",
]
