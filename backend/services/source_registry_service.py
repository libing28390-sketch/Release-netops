"""Source Registry application service for Knowledge Engine V2.

The service is deliberately the only write boundary for ``kb_source_registry``
and ``kb_source_version``.  It canonicalizes URLs before persistence, keeps
tenant predicates on every query, records lifecycle changes in the existing
audit spine, and never performs a network request.  CAT-004 owns the outbound
fetcher; this module only proves that a source is eligible for that later
boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import yaml

import database as _database
from core.rbac import authorize_resource
from database import get_db_connection
from services.audit_service import log_audit_event
from services.source_version_manifest_service import (
    SourceVersionManifestError,
    build_source_version_manifest,
)
from services.ingestion_idempotency_service import (
    build_source_content_identity,
    classify_source_content,
)


REGISTRY_STATUSES = {"draft", "active", "disabled", "archived", "deleted", "quarantined", "purged"}
VERSION_STATUSES = REGISTRY_STATUSES | {"fetched", "verified", "failed"}
SOURCE_TYPES = {"official_vendor", "official_product", "enterprise", "internal", "user_upload", "api"}
SOURCE_KINDS = {
    "official_url",
    "product_page",
    "configuration_guide",
    "command_reference",
    "release_note",
    "product_support",
    "enterprise",
    "internal",
    "user_upload",
    "api",
}
TRUST_LEVELS = {"official", "reviewed", "internal", "untrusted"}

_CAT_SOURCE_KIND_TO_TYPE = {
    "official_url": "official_vendor",
    "product_page": "official_product",
    "configuration_guide": "official_product",
    "command_reference": "official_product",
    "release_note": "official_product",
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
_OFFICIAL_KINDS = set(_CAT_SOURCE_KIND_TO_TYPE)
_SENSITIVE_KEY_PARTS = {
    "password",
    "passwd",
    "token",
    "secret",
    "private_key",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_METADATA_BYTES = 256 * 1024
_DEFAULT_COLLECTION_POLICY: dict[str, Any] = {
    "http_methods": ["GET", "HEAD"],
    "user_agent": "NexoraKnowledgeEngine/2.0",
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
    """Stable, user-safe error returned by the source registry boundary."""

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


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


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
    raw = str(value or "").strip()
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
    # Do not preserve encoded traversal or separator bytes.  A proxy/origin
    # may decode them before routing, which could otherwise turn an apparently
    # descendant redirect into a sibling or parent path after the allowlist
    # check.  Literal backslashes are rejected for the same reason.
    if "\\" in path or re.search(r"(?i)%2e|%2f|%5c", path):
        raise SourceRegistryError("URL_PATH_ENCODING_FORBIDDEN", "Encoded path traversal or separators are not allowed")
    # Normalize dot segments without decoding percent-encoded data.
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
    path = Path(__file__).resolve().parents[2] / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceRegistryError("ALLOWLIST_UNAVAILABLE", "Official source allowlist is unavailable", status_code=503) from exc
    entries: dict[str, list[dict[str, Any]]] = {}
    for vendor in document.get("vendor_entries") or []:
        vendor_name = str(vendor.get("vendor") or "")
        for host_entry in vendor.get("official_hosts") or []:
            host = str(host_entry.get("host") or "").strip().lower()
            if not host or "*" in host:
                continue
            entries.setdefault(host, []).append(
                {
                    "vendor": vendor_name,
                    "vendor_key": str(vendor.get("vendor_key") or ""),
                    "product_family": str(vendor.get("product_family") or ""),
                    "platform_code": str(vendor.get("platform_code") or ""),
                    "os_family": str(vendor.get("os_family") or ""),
                    "path_prefixes": [str(item) for item in host_entry.get("path_prefixes") or []],
                    "allowed_source_kinds": set(str(item) for item in vendor.get("allowed_source_kinds") or []),
                }
            )
    return entries


def _normalize_type(source_type: Any, source_kind: Any = None) -> tuple[str, str]:
    raw_type = str(source_type or "").strip().lower()
    raw_kind = str(source_kind or "").strip().lower()
    if raw_type in _CAT_SOURCE_KIND_TO_TYPE:
        mapped_type = _CAT_SOURCE_KIND_TO_TYPE[raw_type]
        if raw_kind and raw_kind != raw_type:
            raise SourceRegistryError("SOURCE_TYPE_KIND_MISMATCH", "source_type and source_kind describe different source classes")
        return mapped_type, raw_type
    if raw_type not in SOURCE_TYPES:
        raise SourceRegistryError("UNKNOWN_SOURCE_TYPE", "source_type is not in the source registry allowlist")
    if not raw_kind:
        raw_kind = _TYPE_DEFAULT_KIND[raw_type]
    if raw_kind not in SOURCE_KINDS:
        raise SourceRegistryError("UNKNOWN_SOURCE_KIND", "source_kind is not in the CAT-002 taxonomy")
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
        metadata.setdefault("reviewer", str(user.get("username") or _actor(user)))
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
    methods = [str(item).strip().upper() for item in policy.get("http_methods") or []]
    if not methods or any(item not in {"GET", "HEAD"} for item in methods):
        raise SourceRegistryError("HTTP_METHOD_FORBIDDEN", "collection_policy.http_methods may contain only GET and HEAD")
    if len(set(methods)) != len(methods):
        raise SourceRegistryError("HTTP_METHOD_DUPLICATE", "collection_policy.http_methods must not contain duplicates")
    policy["http_methods"] = methods
    user_agent = str(policy.get("user_agent") or "").strip()
    if not user_agent or len(user_agent) > 256 or _CONTROL_RE.search(user_agent):
        raise SourceRegistryError("INVALID_USER_AGENT", "collection_policy.user_agent is required and bounded")
    policy["user_agent"] = user_agent
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
    parser_name = str(policy.get("parser_name") or "").strip()
    parser_version = str(policy.get("parser_version") or "").strip()
    if not parser_name or not parser_version or len(parser_name) > 128 or len(parser_version) > 64:
        raise SourceRegistryError("PARSER_PIN_REQUIRED", "parser_name and parser_version are required")
    policy["parser_name"] = parser_name
    policy["parser_version"] = parser_version
    robots_policy = str(policy.get("robots_policy") or "").strip().lower()
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
    policy["retry_policy"] = {
        "max_attempts": max_attempts,
        "retry_4xx": False,
        "retry_5xx": bool(retry.get("retry_5xx", True)),
    }
    return policy


def _policy_hash(policy: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(policy).encode("utf-8")).hexdigest()


def _tenant_for_user(user: dict[str, Any], requested: str | None = None, *, allow_all: bool = False) -> str | None:
    user_tenant = str(user.get("tenant_id") or "").strip()
    role = str(user.get("role") or "")
    if requested:
        requested = str(requested).strip()
        if not requested:
            requested = None
    if role != "Administrator" and str(user.get("role_profile") or "") != "System Administrator":
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
        raise SourceRegistryError("SOURCE_PERMISSION_DENIED", "Insufficient permission for this source registry operation", status_code=403)


def _scope_sql(user: dict[str, Any], tenant_id: str | None = None, *, allow_all_admin: bool = False) -> tuple[str, list[Any], str | None]:
    scoped_tenant = _tenant_for_user(user, tenant_id, allow_all=allow_all_admin)
    if scoped_tenant is None:
        return "", [], None
    return "tenant_id = ?", [scoped_tenant], scoped_tenant


def _decode_registry(row) -> dict[str, Any] | None:
    item = _row_dict(row)
    if item is None:
        return None
    item["collection_policy"] = _json_load(item.get("collection_policy_json"), {})
    item["metadata"] = _json_load(item.get("metadata_json"), {})
    item["validation"] = _json_load(item.get("validation_json"), {})
    item["fetch_enabled"] = bool(item.get("fetch_enabled"))
    item.pop("collection_policy_json", None)
    item.pop("metadata_json", None)
    item.pop("validation_json", None)
    return item


def _decode_version(row) -> dict[str, Any] | None:
    item = _row_dict(row)
    if item is None:
        return None
    item["metadata"] = _json_load(item.get("metadata_json"), {})
    item["error"] = _json_load(item.get("error_json"), {})
    item.pop("metadata_json", None)
    item.pop("error_json", None)
    return item


def _decode_refresh_observation(row) -> dict[str, Any] | None:
    item = _row_dict(row)
    if item is None:
        return None
    item["metadata"] = _json_load(item.pop("metadata_json", None), {})
    item["error"] = _json_load(item.pop("error_json", None), {})
    item["version_signal"] = _json_load(item.pop("version_signal_json", None), {})
    return item


def _bounded_refresh_text(value: Any, *, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum or _CONTROL_RE.search(text):
        raise SourceRegistryError("INVALID_REFRESH_FIELD", f"{field} is invalid")
    return text


def _is_official_source(source: dict[str, Any]) -> bool:
    return str(source.get("source_type") or "").startswith("official_") or str(source.get("source_kind") or "") in _OFFICIAL_KINDS


def _refresh_url_identity(value: Any) -> tuple[str, int, str]:
    """Return a conservative redirect identity without query/fragment noise.

    The outbound boundary already validated both URLs.  ING-019 treats only a
    host or material path move as a replacement; a trailing slash or a common
    index-document redirect is canonicalization, not a destructive signal.
    """
    canonical = _canonicalize_url(str(value or ""))[0]
    parts = urlsplit(canonical)
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    lowered = path.lower()
    for suffix in ("/index.html", "/index.htm", "/default.html", "/default.htm"):
        if lowered.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/") or "/"
            break
    port = parts.port or 443
    return str(parts.hostname or "").lower(), int(port), path


def _is_material_replacement(source: dict[str, Any], final_url: Any, *, had_baseline: bool) -> bool:
    if not had_baseline or not _is_official_source(source) or not str(final_url or "").strip():
        return False
    return _refresh_url_identity(source.get("canonical_url")) != _refresh_url_identity(final_url)


def record_source_refresh_observation(
    source_id: str,
    payload: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    """Append one redacted conditional-refresh observation.

    Source-version facts remain append-only.  A 304 or a 200 response with an
    already-known hash is therefore represented here rather than by updating
    ``kb_source_version.source_etag`` or ``source_last_modified``.  This also
    gives operations a durable timeline for failed checks without retaining a
    response body.
    """
    request = dict(payload or {})
    conn = get_db_connection()
    source: dict[str, Any] | None = None
    try:
        row = _get_source_in_conn(conn, source_id, user)
        source = _decode_registry(row) or {}
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "create", tenant_id)
        outcome = str(request.get("outcome") or "").strip().lower()
        if outcome not in {"not_modified", "unchanged", "changed", "failed"}:
            raise SourceRegistryError("INVALID_REFRESH_OUTCOME", "Refresh outcome is invalid")
        method = str(request.get("request_method") or "GET").strip().upper()
        if method not in {"GET", "HEAD"}:
            raise SourceRegistryError("INVALID_REFRESH_METHOD", "Refresh method is invalid")
        source_version_id = _bounded_refresh_text(request.get("source_version_id"), field="source_version_id", maximum=128)
        version_fact_hash = ""
        version_fact_size: int | None = None
        if source_version_id:
            version_row = conn.execute(
                "SELECT tenant_id, source_registry_id, content_hash, byte_size FROM kb_source_version WHERE tenant_id = ? AND id = ?",
                (tenant_id, source_version_id),
            ).fetchone()
            if not version_row or str(version_row[1] or "") != str(source_id):
                raise SourceRegistryError("REFRESH_VERSION_NOT_FOUND", "Refresh source version is outside the source scope", status_code=404)
            version_fact_hash = str(version_row[2] or "").lower()
            version_fact_size = int(version_row[3] or 0)
        content_hash = _bounded_refresh_text(request.get("content_hash"), field="content_hash", maximum=64).lower()
        if content_hash and not _SHA256_RE.fullmatch(content_hash):
            raise SourceRegistryError("INVALID_CONTENT_HASH", "Refresh content_hash must be a lowercase SHA-256 digest")
        if source_version_id and not content_hash:
            content_hash = version_fact_hash
        elif source_version_id and content_hash != version_fact_hash:
            raise SourceRegistryError("REFRESH_VERSION_FACT_MISMATCH", "Refresh content hash does not match the immutable source version")
        try:
            byte_size = int(request.get("byte_size") or 0) if "byte_size" in request else int(version_fact_size or 0)
        except (TypeError, ValueError) as exc:
            raise SourceRegistryError("INVALID_BYTE_SIZE", "Refresh byte_size is invalid") from exc
        if byte_size < 0:
            raise SourceRegistryError("INVALID_BYTE_SIZE", "Refresh byte_size is invalid")
        if source_version_id and version_fact_size is not None and byte_size != version_fact_size:
            raise SourceRegistryError("REFRESH_VERSION_FACT_MISMATCH", "Refresh byte size does not match the immutable source version")
        try:
            http_status = int(request["http_status"]) if request.get("http_status") is not None else None
        except (TypeError, ValueError) as exc:
            raise SourceRegistryError("INVALID_HTTP_STATUS", "Refresh HTTP status is invalid") from exc
        if http_status is not None and not 100 <= http_status <= 599:
            raise SourceRegistryError("INVALID_HTTP_STATUS", "Refresh HTTP status is invalid")
        checked_at = _bounded_refresh_text(
            request.get("checked_at") or datetime.now(timezone.utc).isoformat(),
            field="checked_at",
            maximum=128,
        )
        created_at = _now()
        etag = _bounded_refresh_text(request.get("source_etag"), field="source_etag", maximum=512)
        last_modified = _bounded_refresh_text(request.get("source_last_modified"), field="source_last_modified", maximum=256)
        fetch_url = _bounded_refresh_text(request.get("fetch_url"), field="fetch_url", maximum=4096)
        response_type = _bounded_refresh_text(request.get("response_content_type"), field="response_content_type", maximum=256)
        error_code = _bounded_refresh_text(request.get("error_code"), field="error_code", maximum=128)
        detection_type = str(request.get("detection_type") or "none").strip().lower()
        if detection_type not in {"none", "removed", "replacement", "version_updated"}:
            raise SourceRegistryError("INVALID_DETECTION_TYPE", "Refresh detection type is invalid")
        replacement_url = _bounded_refresh_text(request.get("replacement_url"), field="replacement_url", maximum=4096)
        if detection_type != "none" and not _is_official_source(source):
            raise SourceRegistryError("OFFICIAL_SOURCE_REQUIRED", "Only official sources may receive official change detections", status_code=409)
        if detection_type == "replacement" and not replacement_url:
            raise SourceRegistryError("REPLACEMENT_URL_REQUIRED", "Replacement detection requires a validated replacement URL")
        if detection_type != "replacement" and replacement_url:
            raise SourceRegistryError("UNEXPECTED_REPLACEMENT_URL", "replacement_url is only valid for replacement detections")
        if detection_type == "removed" and (outcome != "failed" or http_status not in {404, 410}):
            raise SourceRegistryError("INVALID_REMOVAL_SIGNAL", "Removal detection requires an HTTP 404 or 410 failed observation")
        if detection_type == "version_updated" and outcome != "changed":
            raise SourceRegistryError("INVALID_VERSION_SIGNAL", "Version update detection requires a changed observation")
        error_json = request.get("error") or {}
        metadata = request.get("metadata") or {}
        version_signal = request.get("version_signal") or {}
        if not isinstance(error_json, dict) or not isinstance(metadata, dict) or not isinstance(version_signal, dict):
            raise SourceRegistryError("INVALID_REFRESH_JSON", "Refresh error, metadata and version signal must be objects")
        _assert_no_secrets(error_json)
        _assert_no_secrets(metadata)
        _assert_no_secrets(version_signal)
        if len(_json_dumps(error_json).encode("utf-8")) > 16 * 1024 or len(_json_dumps(metadata).encode("utf-8")) > 64 * 1024 or len(_json_dumps(version_signal).encode("utf-8")) > 16 * 1024:
            raise SourceRegistryError("REFRESH_METADATA_TOO_LARGE", "Refresh metadata is too large")
        observation_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO kb_source_refresh_observation (
                id, tenant_id, source_registry_id, source_version_id, checked_at,
                request_method, http_status, outcome, content_hash, byte_size,
                source_etag, source_last_modified, fetch_url, response_content_type,
                error_code, error_json, metadata_json, created_at, created_by,
                detection_type, replacement_url, version_signal_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id, tenant_id, str(source_id), source_version_id or None,
                checked_at, method, http_status, outcome, content_hash, byte_size,
                etag, last_modified, fetch_url, response_type, error_code,
                _json_dumps(error_json), _json_dumps(metadata), created_at, _actor(user),
                detection_type, replacement_url, _json_dumps(version_signal),
            ),
        )
        observation = conn.execute(
            "SELECT * FROM kb_source_refresh_observation WHERE tenant_id = ? AND id = ?",
            (tenant_id, observation_id),
        ).fetchone()
        action_id = ""
        if detection_type in {"removed", "replacement"}:
            action_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO kb_source_change_action (
                    id, tenant_id, refresh_observation_id, source_registry_id,
                    detection_type, status, attempt_count, last_error_code,
                    created_at, created_by, updated_at, updated_by, applied_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, '', ?, ?, ?, ?, NULL)
                """,
                (
                    action_id, tenant_id, observation_id, str(source_id), detection_type,
                    created_at, _actor(user), created_at, _actor(user),
                ),
            )
        _audit(
            conn,
            event_type="source_refresh_observed",
            user=user,
            source=row,
            after={"refresh_observation_id": observation_id, "change_action_id": action_id or None, "outcome": outcome, "http_status": http_status},
            details={"outcome": outcome, "http_status": http_status, "content_hash": content_hash, "detection_type": detection_type},
        )
        conn.commit()
        decoded = _decode_refresh_observation(observation) or {}
        if action_id:
            decoded["change_action_id"] = action_id
        return decoded
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_source_refresh_observations(
    source_id: str,
    user: dict[str, Any],
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bounded, tenant-scoped freshness history for operations."""
    source_id = _bounded_refresh_text(source_id, field="source_id", maximum=128)
    try:
        bounded_limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError("INVALID_REFRESH_LIMIT", "Refresh history limit is invalid") from exc
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "read", tenant_id)
        rows = conn.execute(
            "SELECT * FROM kb_source_refresh_observation WHERE tenant_id = ? AND source_registry_id = ? ORDER BY checked_at DESC, id DESC LIMIT ?",
            (tenant_id, source_id, bounded_limit),
        ).fetchall()
        return [_decode_refresh_observation(row) for row in rows]
    finally:
        conn.close()


def _get_source_in_conn(conn, source_id: str, user: dict[str, Any], *, tenant_id: str | None = None, for_update: bool = False):
    clauses = ["id = ?"]
    params: list[Any] = [str(source_id)]
    scope_sql, scope_params, _ = _scope_sql(user, tenant_id)
    if scope_sql:
        clauses.append(scope_sql)
        params.extend(scope_params)
    sql = "SELECT * FROM kb_source_registry WHERE " + " AND ".join(clauses)
    if for_update and _database._USE_PG:
        sql += " FOR UPDATE"
    row = conn.execute(sql, params).fetchone()
    if not row:
        raise SourceRegistryError("SOURCE_NOT_FOUND", "Source registry record was not found", status_code=404)
    return _row_dict(row)


def _audit(conn, *, event_type: str, user: dict[str, Any], source: dict[str, Any], before: dict[str, Any] | None = None, after: dict[str, Any] | None = None, details: dict[str, Any] | None = None) -> None:
    log_audit_event(
        event_type=event_type,
        category="knowledge_source",
        severity="info",
        status="success",
        summary=f"Knowledge source {event_type.replace('source_', '')}",
        actor_id=_actor(user),
        actor_username=str(user.get("username") or _actor(user)),
        actor_role=str(user.get("role") or "system"),
        target_type="kb_source_registry",
        target_id=str(source.get("id") or ""),
        target_name=str(source.get("name") or source.get("canonical_url") or ""),
        before=before,
        after=after,
        details=details or {},
        conn=conn,
    )


def _official_match(row: dict[str, Any], *, canonical_host: str, path: str) -> tuple[bool, list[str], dict[str, Any] | None]:
    errors: list[str] = []
    entries = _load_official_allowlist().get(canonical_host, [])
    source_kind = str(row.get("source_kind") or "")
    match = None
    for entry in entries:
        if source_kind not in entry["allowed_source_kinds"] and source_kind not in {"official_url", "product_page", "product_support"}:
            continue
        if any(path.startswith(prefix) for prefix in entry["path_prefixes"]):
            match = entry
            break
    if not match:
        errors.append("canonical_url_is_outside_CAT001_host_path_allowlist")
        return False, errors, None
    metadata = _json_load(row.get("metadata_json"), {})
    vendor = str(metadata.get("vendor") or "").strip().lower()
    if vendor and vendor not in {str(match.get("vendor") or "").lower(), str(match.get("vendor_key") or "").lower()}:
        errors.append("metadata_vendor_does_not_match_official_allowlist")
    product_family = str(metadata.get("product_family") or "").strip()
    if product_family and product_family.lower() != str(match.get("product_family") or "").lower():
        errors.append("metadata_product_family_does_not_match_official_allowlist")
    kind = source_kind
    if kind in _OFFICIAL_KINDS and kind not in entry["allowed_source_kinds"] and kind not in {"official_url", "product_page", "product_support"}:
        errors.append("source_kind_is_not_allowed_for_official_entry")
    if match is not None:
        match = {**match, "allowed_source_kinds": sorted(match.get("allowed_source_kinds") or [])}
    return not errors, errors, match


def _validate_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, bool] = {}
    try:
        canonical, host, port, path = _canonicalize_url(row.get("canonical_url"))
    except SourceRegistryError as exc:
        return {"valid": False, "errors": [exc.code], "checks": {"url": False}}
    checks["url"] = canonical == str(row.get("canonical_url") or "")
    if not checks["url"]:
        errors.append("canonical_url_is_not_normalized")
    checks["allowed_host"] = str(row.get("allowed_host") or "").lower() == host and "*" not in str(row.get("allowed_host") or "")
    if not checks["allowed_host"]:
        errors.append("allowed_host_does_not_match_canonical_url")
    checks["https_443"] = str(row.get("allowed_scheme") or "https").lower() == "https" and int(row.get("allowed_port") or 443) == 443 and port == 443
    if not checks["https_443"]:
        errors.append("source_must_use_https_port_443")
    try:
        policy = _normalize_policy(_json_load(row.get("collection_policy_json"), {}))
        checks["policy"] = True
    except SourceRegistryError as exc:
        checks["policy"] = False
        errors.append(exc.code)
        policy = {}
    source_type = str(row.get("source_type") or "")
    source_kind = str(row.get("source_kind") or "")
    checks["source_type"] = source_type in SOURCE_TYPES and source_kind in SOURCE_KINDS
    if not checks["source_type"]:
        errors.append("unknown_source_type_or_kind")
    checks["secret_free"] = True
    try:
        _assert_no_secrets(_json_load(row.get("metadata_json"), {}))
        _assert_no_secrets(_json_load(row.get("collection_policy_json"), {}))
    except SourceRegistryError as exc:
        checks["secret_free"] = False
        errors.append(exc.code)
    official_entry = None
    if source_type in {"official_vendor", "official_product"} or source_kind in _OFFICIAL_KINDS:
        official_ok, official_errors, official_entry = _official_match(row, canonical_host=host, path=path)
        checks["official_allowlist"] = official_ok
        errors.extend(official_errors)
        metadata = _json_load(row.get("metadata_json"), {})
        scope = metadata.get("version_scope") or {}
        scope_ok = isinstance(scope, dict) and bool(str(scope.get("primary") or "").strip()) and bool(str(scope.get("compatibility") or "").strip())
        checks["version_scope"] = scope_ok
        if not scope_ok:
            errors.append("primary_and_compatibility_version_scope_required")
        terms_ok = str(metadata.get("terms_review_status") or "").lower() in {"approved", "waived", "not_required"}
        checks["terms_review"] = terms_ok
        if not terms_ok:
            errors.append("terms_review_not_approved")
    else:
        checks["official_allowlist"] = True
        checks["version_scope"] = True
        checks["terms_review"] = True
    # Keep the normalized policy in the result for callers, but never persist
    # it here; validation itself is a separate audited mutation.
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "checks": checks,
        "canonical_url": canonical,
        "allowed_host": host,
        "allowed_port": port,
        "policy_hash": _policy_hash(policy) if policy else "",
        "official_entry": official_entry,
    }


def validate_official_url_input(
    canonical_url: str,
    *,
    source_kind: str = "product_page",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one official URL before creating a registry row.

    ING-002 uses this preflight to avoid leaving a draft source behind for an
    unallowlisted host/path.  It performs no network request and returns only
    allowlist metadata needed to build the source record.
    """
    normalized_kind = str(source_kind or "product_page").strip().lower()
    source_type, normalized_kind = _normalize_type(
        "official_vendor" if normalized_kind == "official_url" else "official_product",
        normalized_kind,
    )
    canonical, host, port, _ = _canonicalize_url(canonical_url)
    safe_metadata = copy.deepcopy(metadata or {})
    if not isinstance(safe_metadata, dict):
        raise SourceRegistryError("INVALID_METADATA", "metadata must be an object")
    _assert_no_secrets(safe_metadata)
    row = {
        "source_type": source_type,
        "source_kind": normalized_kind,
        "canonical_url": canonical,
        "allowed_host": host,
        "allowed_scheme": "https",
        "allowed_port": port,
        "collection_policy_json": _json_dumps(_normalize_policy(None)),
        "metadata_json": _json_dumps(safe_metadata),
    }
    result = _validate_registry_row(row)
    if not result["valid"]:
        code = "OFFICIAL_URL_NOT_ALLOWLISTED" if not result.get("checks", {}).get("official_allowlist", False) else "OFFICIAL_URL_METADATA_INVALID"
        raise SourceRegistryError(
            code,
            "Official URL did not pass the reviewed source registry gate",
            status_code=403,
            details={"errors": result.get("errors", []), "checks": result.get("checks", {})},
        )
    return {
        "canonical_url": canonical,
        "allowed_host": host,
        "allowed_port": port,
        "source_type": source_type,
        "source_kind": normalized_kind,
        "official_entry": result.get("official_entry"),
    }


def create_source(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant_for_user(user, str(payload.get("tenant_id") or "") or None)
    _authorize(user, "create", tenant_id)
    if not tenant_id:
        raise SourceRegistryError("TENANT_REQUIRED", "An explicit tenant scope is required")
    source_type, source_kind = _normalize_type(payload.get("source_type"), payload.get("source_kind"))
    canonical_url, host, port, _ = _canonicalize_url(payload.get("canonical_url"))
    allowed_host = str(payload.get("allowed_host") or host).strip().rstrip(".").lower()
    if allowed_host != host or "*" in allowed_host:
        raise SourceRegistryError("ALLOWED_HOST_MISMATCH", "allowed_host must exactly match canonical_url hostname")
    now = _now()
    policy = _normalize_policy(payload.get("collection_policy"))
    metadata = _normalize_metadata(payload.get("metadata"), user=user, source_type=source_type, now=now)
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if len(name) > 256 or len(description) > 4_000:
        raise SourceRegistryError("SOURCE_TEXT_TOO_LONG", "Source name or description is too long")
    trust_level = str(payload.get("trust_level") or ("official" if source_type.startswith("official_") else "reviewed")).strip().lower()
    if trust_level not in TRUST_LEVELS:
        raise SourceRegistryError("UNKNOWN_TRUST_LEVEL", "trust_level is not in the source registry allowlist")
    if source_type.startswith("official_") and trust_level != "official":
        raise SourceRegistryError("OFFICIAL_TRUST_REQUIRED", "Official catalog sources must use trust_level=official")
    requested_status = str(payload.get("status") or "draft").strip().lower()
    if requested_status != "draft":
        raise SourceRegistryError("CREATE_MUST_START_DRAFT", "New sources must start in draft status")
    source_id = str(uuid.uuid4())
    actor = _actor(user)
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO kb_source_registry (
                id, tenant_id, source_type, source_kind, name, description,
                canonical_url, allowed_host, allowed_scheme, allowed_port,
                host_match_mode, trust_level, collection_policy_json,
                fetch_enabled, max_bytes, timeout_seconds, redirect_limit,
                rate_limit_per_minute, policy_version, policy_hash, metadata_json,
                validation_status, validation_json, created_at, updated_at,
                created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'https', ?, 'exact', ?, ?, 0, ?, ?, ?, ?, 1, ?, ?, 'unvalidated', '{}', ?, ?, ?, ?)
            """,
            (
                source_id, tenant_id, source_type, source_kind, name, description,
                canonical_url, allowed_host, port, trust_level, _json_dumps(policy),
                policy["max_bytes"], policy["timeout_seconds"], policy["redirect_limit"],
                policy["rate_limit_per_minute"], _policy_hash(policy), _json_dumps(metadata),
                now, now, actor, actor,
            ),
        )
        source = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(conn, event_type="source_created", user=user, source=source, after=_decode_registry(source))
        conn.commit()
        return _decode_registry(source) or {}
    except SourceRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper() or "DUPLICATE" in str(exc).upper():
            raise SourceRegistryError("SOURCE_URL_CONFLICT", "A source with this URL already exists in the tenant", status_code=409) from exc
        raise
    finally:
        conn.close()


def list_sources(user: dict[str, Any], *, status: str = "all", tenant_id: str | None = None) -> list[dict[str, Any]]:
    _authorize(user, "read", _tenant_for_user(user, tenant_id, allow_all=True))
    status = str(status or "all").strip().lower()
    if status != "all" and status not in REGISTRY_STATUSES:
        raise SourceRegistryError("UNKNOWN_STATUS", "status is not in the source registry lifecycle allowlist")
    scope_sql, params, _ = _scope_sql(user, tenant_id, allow_all_admin=True)
    clauses: list[str] = []
    if scope_sql:
        clauses.append(scope_sql)
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    else:
        clauses.append("status <> 'purged'")
    where = " AND ".join(clauses) or "1=1"
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT * FROM kb_source_registry WHERE {where} ORDER BY updated_at DESC, id", params).fetchall()
        return [_decode_registry(row) for row in rows]
    finally:
        conn.close()


def get_source(source_id: str, user: dict[str, Any], *, tenant_id: str | None = None) -> dict[str, Any]:
    _authorize(user, "read", _tenant_for_user(user, tenant_id, allow_all=True))
    conn = get_db_connection()
    try:
        row = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        return _decode_registry(row) or {}
    finally:
        conn.close()


def update_source(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "update", tenant_id)
        expected = payload.get("expected_updated_at")
        if expected and str(expected) != str(source.get("updated_at") or ""):
            raise SourceRegistryError("STALE_SOURCE", "Source was changed by another request", status_code=409)
        updates: dict[str, Any] = {}
        if "canonical_url" in payload and payload.get("canonical_url") is not None:
            canonical, host, _, _ = _canonicalize_url(payload.get("canonical_url"))
            if canonical != str(source.get("canonical_url") or "") or host != str(source.get("allowed_host") or ""):
                raise SourceRegistryError("SOURCE_IDENTITY_IMMUTABLE", "Changing canonical_url requires a new source registry row", status_code=409)
        for key, limit in (("name", 256), ("description", 4_000)):
            if key in payload and payload[key] is not None:
                value = str(payload[key]).strip()
                if len(value) > limit:
                    raise SourceRegistryError("SOURCE_TEXT_TOO_LONG", f"{key} is too long")
                updates[key] = value
        if "trust_level" in payload and payload["trust_level"] is not None:
            trust = str(payload["trust_level"]).strip().lower()
            if trust not in TRUST_LEVELS:
                raise SourceRegistryError("UNKNOWN_TRUST_LEVEL", "trust_level is not in the source registry allowlist")
            if str(source.get("source_type") or "").startswith("official_") and trust != "official":
                raise SourceRegistryError("OFFICIAL_TRUST_REQUIRED", "Official catalog sources must use trust_level=official")
            updates["trust_level"] = trust
        metadata = _json_load(source.get("metadata_json"), {})
        if "metadata" in payload and payload["metadata"] is not None:
            if not isinstance(payload["metadata"], dict):
                raise SourceRegistryError("INVALID_METADATA", "metadata must be an object")
            metadata.update(copy.deepcopy(payload["metadata"]))
            _assert_no_secrets(metadata)
            if len(_json_dumps(metadata).encode("utf-8")) > _MAX_METADATA_BYTES:
                raise SourceRegistryError("METADATA_TOO_LARGE", "metadata exceeds the 256 KiB limit")
            updates["metadata_json"] = _json_dumps(metadata)
        policy_changed = "collection_policy" in payload and payload["collection_policy"] is not None
        if policy_changed:
            policy = _normalize_policy(payload["collection_policy"])
            updates.update(
                {
                    "collection_policy_json": _json_dumps(policy),
                    "max_bytes": policy["max_bytes"],
                    "timeout_seconds": policy["timeout_seconds"],
                    "redirect_limit": policy["redirect_limit"],
                    "rate_limit_per_minute": policy["rate_limit_per_minute"],
                    "policy_hash": _policy_hash(policy),
                    "policy_version": int(source.get("policy_version") or 1) + 1,
                    "validation_status": "unvalidated",
                    "validation_json": "{}",
                    "fetch_enabled": 0,
                }
            )
            if str(source.get("status") or "") == "active":
                updates["status"] = "disabled"
        if not updates:
            return _decode_registry(source) or {}
        now = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = [updates[key] for key in updates]
        conn.execute(
            f"UPDATE kb_source_registry SET {assignments}, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
            (*values, now, _actor(user), source_id, tenant_id),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(conn, event_type="policy_changed" if policy_changed else "source_updated", user=user, source=updated, before=_decode_registry(source), after=_decode_registry(updated))
        conn.commit()
        return _decode_registry(updated) or {}
    except SourceRegistryError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_source(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        _authorize(user, "read", str(source.get("tenant_id") or ""))
        result = _validate_registry_row(source)
        now = _now()
        conn.execute(
            "UPDATE kb_source_registry SET validation_status = ?, validation_json = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
            ("valid" if result["valid"] else "invalid", _json_dumps(result), now, _actor(user), source_id, source.get("tenant_id")),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=str(source.get("tenant_id") or ""))
        _audit(conn, event_type="source_updated", user=user, source=updated, before=_decode_registry(source), after=_decode_registry(updated), details={"validation": result})
        conn.commit()
        result["source"] = _decode_registry(updated)
        return result
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def enable_source(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "update", tenant_id)
        status = str(source.get("status") or "")
        if status not in {"draft", "disabled"}:
            raise SourceRegistryError("INVALID_STATUS_TRANSITION", f"Cannot enable source from status {status}", status_code=409)
        result = _validate_registry_row(source)
        now = _now()
        if not result["valid"]:
            conn.execute(
                "UPDATE kb_source_registry SET validation_status = 'invalid', validation_json = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
                (_json_dumps(result), now, _actor(user), source_id, tenant_id),
            )
            conn.commit()
            raise SourceRegistryError("SOURCE_VALIDATION_FAILED", "Source did not pass validation and remains non-active", status_code=409, details=result)
        conn.execute(
            "UPDATE kb_source_registry SET status = 'active', fetch_enabled = 1, validation_status = 'valid', validation_json = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1, disabled_at = NULL, disabled_by = NULL, disable_reason = NULL WHERE id = ? AND tenant_id = ?",
            (_json_dumps(result), now, _actor(user), source_id, tenant_id),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(conn, event_type="source_enabled", user=user, source=updated, before=_decode_registry(source), after=_decode_registry(updated), details={"validation": result})
        conn.commit()
        return _decode_registry(updated) or {}
    except SourceRegistryError:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        conn.close()


def disable_source(source_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "update", tenant_id)
        if str(source.get("status") or "") != "active":
            raise SourceRegistryError("INVALID_STATUS_TRANSITION", "Only active sources may be disabled", status_code=409)
        reason = str(reason or "").strip()
        if len(reason) > 2_000:
            raise SourceRegistryError("REASON_TOO_LONG", "disable reason is too long")
        now = _now()
        conn.execute(
            "UPDATE kb_source_registry SET status = 'disabled', fetch_enabled = 0, disabled_at = ?, disabled_by = ?, disable_reason = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
            (now, _actor(user), reason, now, _actor(user), source_id, tenant_id),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(conn, event_type="source_disabled", user=user, source=updated, before=_decode_registry(source), after=_decode_registry(updated), details={"reason": reason})
        conn.commit()
        return _decode_registry(updated) or {}
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def quarantine_source_for_change(
    source_id: str,
    user: dict[str, Any],
    *,
    detection_type: str,
    reason_code: str,
    replacement_url: str = "",
    refresh_observation_id: str = "",
) -> dict[str, Any]:
    """Quarantine an official source after a removal/replacement signal.

    This is an additive, auditable state transition for the ING-019 detector;
    it never deletes a source or rewrites immutable Source Version facts.
    """
    detection_type = str(detection_type or "").strip().lower()
    if detection_type not in {"removed", "replacement"}:
        raise SourceRegistryError("INVALID_DETECTION_TYPE", "Only removal or replacement can quarantine a source")
    reason_code = _bounded_refresh_text(reason_code, field="reason_code", maximum=128)
    replacement_url = _bounded_refresh_text(replacement_url, field="replacement_url", maximum=4096)
    refresh_observation_id = _bounded_refresh_text(refresh_observation_id, field="refresh_observation_id", maximum=128)
    conn = get_db_connection()
    try:
        source_row = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source_row.get("tenant_id") or "")
        _authorize(user, "update", tenant_id)
        source_type = str(source_row.get("source_type") or "")
        source_kind = str(source_row.get("source_kind") or "")
        if not source_type.startswith("official_") and source_kind not in _OFFICIAL_KINDS:
            raise SourceRegistryError("OFFICIAL_SOURCE_REQUIRED", "Only official sources may be quarantined by the detector", status_code=409)
        status = str(source_row.get("status") or "")
        if status == "quarantined":
            return _decode_registry(source_row) or {}
        now = _now()
        validation = {
            "detector": "ING-019",
            "detection_type": detection_type,
            "reason_code": reason_code,
            "replacement_present": bool(replacement_url),
            "refresh_observation_id": refresh_observation_id,
        }
        conn.execute(
            "UPDATE kb_source_registry SET status = 'quarantined', fetch_enabled = 0, validation_status = 'invalid', validation_json = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
            (_json_dumps(validation), now, _actor(user), source_id, tenant_id),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(
            conn,
            event_type="source_quarantined",
            user=user,
            source=updated,
            before=_decode_registry(source_row),
            after=_decode_registry(updated),
            details={
                "detection_type": detection_type,
                "reason_code": reason_code,
                "replacement_present": bool(replacement_url),
                "refresh_observation_id": refresh_observation_id,
            },
        )
        conn.commit()
        return _decode_registry(updated) or {}
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_source(source_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "delete", tenant_id)
        if str(source.get("status") or "") == "purged":
            raise SourceRegistryError("SOURCE_PURGED", "Purged sources cannot be changed", status_code=409)
        reason = str(reason or "").strip()
        now = _now()
        conn.execute(
            "UPDATE kb_source_registry SET status = 'deleted', fetch_enabled = 0, deleted_at = ?, deleted_by = ?, deletion_reason = ?, updated_at = ?, updated_by = ?, lock_version = lock_version + 1 WHERE id = ? AND tenant_id = ?",
            (now, _actor(user), reason, now, _actor(user), source_id, tenant_id),
        )
        updated = _get_source_in_conn(conn, source_id, user, tenant_id=tenant_id)
        _audit(conn, event_type="source_deleted", user=user, source=updated, before=_decode_registry(source), after=_decode_registry(updated), details={"soft_delete": True, "reason": reason})
        conn.commit()
        return _decode_registry(updated) or {}
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_source_version(source_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source.get("tenant_id") or "")
        _authorize(user, "create", tenant_id)
        if str(source.get("status") or "") != "active" or not bool(source.get("fetch_enabled")):
            raise SourceRegistryError("SOURCE_NOT_ACTIVE", "Source versions may only be recorded for an active source", status_code=409)
        content = payload.get("content")
        content_bytes: bytes | None = None
        if content is not None:
            if isinstance(content, bytes):
                content_bytes = content
            elif isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                raise SourceRegistryError("INVALID_CONTENT", "content must be UTF-8 text or bytes")
        supplied_hash = str(payload.get("content_hash") or "").strip().lower()
        computed_hash = hashlib.sha256(content_bytes).hexdigest() if content_bytes is not None else ""
        content_hash = supplied_hash or computed_hash
        if not _SHA256_RE.fullmatch(content_hash):
            raise SourceRegistryError("INVALID_CONTENT_HASH", "content_hash must be a lowercase SHA-256 hex digest")
        if content_bytes is not None and content_hash != computed_hash:
            raise SourceRegistryError("CONTENT_HASH_MISMATCH", "content_hash does not match content")
        try:
            byte_size = int(payload.get("byte_size")) if payload.get("byte_size") is not None else (len(content_bytes) if content_bytes is not None else -1)
        except (TypeError, ValueError) as exc:
            raise SourceRegistryError("INVALID_BYTE_SIZE", "byte_size must be a non-negative integer") from exc
        if byte_size < 0 or (content_bytes is not None and byte_size != len(content_bytes)):
            raise SourceRegistryError("BYTE_SIZE_MISMATCH", "byte_size must match retained content or its verified reference")
        parser_name = str(payload.get("parser_name") or "").strip()
        parser_version = str(payload.get("parser_version") or "").strip()
        if not parser_name or not parser_version or len(parser_name) > 128 or len(parser_version) > 64:
            raise SourceRegistryError("PARSER_PIN_REQUIRED", "parser_name and parser_version are required")
        version_status = str(payload.get("status") or "fetched").strip().lower()
        if version_status not in {"draft", "fetched", "verified", "failed", "quarantined"}:
            raise SourceRegistryError("INVALID_VERSION_STATUS", "source version status is not allowed")
        fetch_url = payload.get("fetch_url") or source.get("canonical_url")
        canonical_fetch, fetch_host, _, _ = _canonicalize_url(fetch_url)
        source_path = (urlsplit(str(source.get("canonical_url") or "")).path or "/").rstrip("/") or "/"
        fetch_path = (urlsplit(canonical_fetch).path or "/").rstrip("/") or "/"
        same_registered_path = fetch_path == source_path or fetch_path.startswith(source_path.rstrip("/") + "/")
        if fetch_host != str(source.get("allowed_host") or "") or not same_registered_path:
            raise SourceRegistryError("FETCH_URL_OUTSIDE_SOURCE", "fetch_url is outside the registered source boundary")
        raw_ref = str(payload.get("raw_content_ref") or "").strip()
        metadata = payload.get("metadata") or {}
        error_json = payload.get("error") or {}
        if not isinstance(metadata, dict) or not isinstance(error_json, dict):
            raise SourceRegistryError("INVALID_VERSION_JSON", "version metadata and error must be objects")
        _assert_no_secrets(metadata)
        _assert_no_secrets(error_json)
        now = _now()
        fetched_at = str(payload.get("fetched_at") or now).strip()
        if not fetched_at or _CONTROL_RE.search(fetched_at):
            raise SourceRegistryError("INVALID_FETCHED_AT", "fetched_at must be a safe timestamp string")
        try:
            manifest = build_source_version_manifest(
                source,
                content_hash=content_hash,
                byte_size=byte_size,
                fetched_at=fetched_at,
                parser_name=parser_name,
                parser_version=parser_version,
                fetch_url=canonical_fetch,
                source_etag=str(payload.get("source_etag") or ""),
                source_last_modified=str(payload.get("source_last_modified") or ""),
                response_content_type=str(payload.get("response_content_type") or ""),
                http_status=payload.get("http_status"),
                raw_content_ref=raw_ref,
                raw_content_storage=str(payload.get("raw_content_storage") or ""),
                verification_method=str(payload.get("verification_method") or ""),
                status=version_status,
            )
        except SourceVersionManifestError as exc:
            raise SourceRegistryError(exc.code, exc.message, details=exc.details) from exc
        # The manifest is server-owned provenance.  Caller metadata remains
        # useful for bounded collection details, but cannot replace these
        # source/hash/time/HTTP/parser facts.
        metadata = dict(metadata)
        metadata["source_manifest"] = manifest
        persisted_raw_storage = str(manifest["raw_content"]["storage"])
        existing = conn.execute(
            "SELECT * FROM kb_source_version WHERE tenant_id = ? AND source_registry_id = ? AND content_hash = ?",
            (tenant_id, source_id, content_hash),
        ).fetchone()
        if existing:
            conn.rollback()
            result = _decode_version(existing) or {}
            result["deduplicated"] = True
            identity = build_source_content_identity(
                tenant_id=tenant_id,
                source_id=source_id,
                canonical_url=str(source.get("canonical_url") or ""),
                content_hash=content_hash,
                byte_size=byte_size,
            )
            result["idempotency"] = classify_source_content(result, identity=identity).as_dict()
            return result
        version_id = str(uuid.uuid4())
        actor = _actor(user)
        conn.execute(
            """
            INSERT INTO kb_source_version (
                id, tenant_id, source_registry_id, fetched_at, content_hash,
                byte_size, parser_name, parser_version, source_etag,
                source_last_modified, fetch_url, response_content_type,
                http_status, raw_content_ref, raw_content_storage,
                verified_at, verification_method, error_code, error_json,
                metadata_json, status, created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id, tenant_id, source_id, fetched_at, content_hash,
                byte_size, parser_name, parser_version,
                str(payload.get("source_etag") or ""), str(payload.get("source_last_modified") or ""),
                canonical_fetch, str(payload.get("response_content_type") or ""), payload.get("http_status"),
                raw_ref, persisted_raw_storage,
                now if version_status == "verified" else None, str(payload.get("verification_method") or ""),
                str(payload.get("error_code") or ""), _json_dumps(error_json), _json_dumps(metadata),
                version_status, now, now, actor, actor,
            ),
        )
        version = conn.execute("SELECT * FROM kb_source_version WHERE id = ? AND tenant_id = ?", (version_id, tenant_id)).fetchone()
        _audit(conn, event_type="fetch_completed", user=user, source=source, after={"source_version_id": version_id, "content_hash": content_hash, "status": version_status}, details={"byte_size": byte_size, "parser_name": parser_name, "parser_version": parser_version})
        conn.commit()
        result = _decode_version(version) or {}
        identity = build_source_content_identity(
            tenant_id=tenant_id,
            source_id=source_id,
            canonical_url=str(source.get("canonical_url") or ""),
            content_hash=content_hash,
            byte_size=byte_size,
        )
        result["idempotency"] = classify_source_content(None, identity=identity).as_dict()
        return result
    except SourceRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper() or "DUPLICATE" in str(exc).upper():
            existing = conn.execute(
                "SELECT * FROM kb_source_version WHERE tenant_id = ? AND source_registry_id = ? AND content_hash = ?",
                (str(source.get("tenant_id") or ""), source_id, str(payload.get("content_hash") or "").lower()),
            ).fetchone()
            if existing:
                result = _decode_version(existing) or {}
                result["deduplicated"] = True
                identity = build_source_content_identity(
                    tenant_id=str(source.get("tenant_id") or ""),
                    source_id=source_id,
                    canonical_url=str(source.get("canonical_url") or ""),
                    content_hash=content_hash,
                    byte_size=byte_size,
                )
                result["idempotency"] = classify_source_content(result, identity=identity).as_dict()
                return result
        raise
    finally:
        conn.close()


def collect_source(
    source_id: str,
    payload: dict[str, Any] | None,
    user: dict[str, Any],
    *,
    transport: Any = None,
    resolver: Any = None,
    client_factory: Any = None,
) -> dict[str, Any]:
    """Collect an active registry source through the CAT-004 safe boundary.

    The network helper is injectable only for deterministic tests.  The public
    API never accepts a transport, resolver or client factory, so production
    calls always use the fail-closed resolver and an HTTPX client with proxy
    environment variables disabled.  Response bodies are held only in memory
    long enough to compute the immutable SHA-256 version fact; the API returns
    metadata and never returns the body.
    """
    request = dict(payload or {})
    method = str(request.get("method") or "GET").strip().upper()
    conn = get_db_connection()
    latest_version: dict[str, Any] = {}
    try:
        source_row = _get_source_in_conn(conn, source_id, user, for_update=True)
        tenant_id = str(source_row.get("tenant_id") or "")
        _authorize(user, "create", tenant_id)
        source = _decode_registry(source_row) or {}
        latest_row = conn.execute(
            "SELECT * FROM kb_source_version WHERE tenant_id = ? AND source_registry_id = ? AND status IN ('fetched','verified') ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (tenant_id, source_id),
        ).fetchone()
        latest_version = _decode_version(latest_row) or {}
    finally:
        conn.close()

    def _audit_fetch(event_type: str, *, details: dict[str, Any], after: dict[str, Any] | None = None) -> None:
        audit_conn = get_db_connection()
        try:
            _audit(
                audit_conn,
                event_type=event_type,
                user=user,
                source=source,
                after=after,
                details=details,
            )
            audit_conn.commit()
        finally:
            audit_conn.close()

    def _apply_change_detection(
        *,
        detection_type: str,
        observation: dict[str, Any],
        reason_code: str,
        replacement_url: str = "",
        source_version_id: str = "",
    ) -> dict[str, Any]:
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
                "applied": False,
                "detection_type": detection_type,
                "action_id": str(observation.get("change_action_id") or ""),
                "action_status": "failed",
                "error_code": str(exc.code or "SOURCE_CHANGE_APPLY_FAILED")[:128],
            }

    _audit_fetch(
        "fetch_started",
        details={"method": method, "policy_version": source.get("policy_version")},
    )
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    try:
        result = safe_fetch(
            source,
            method=method,
            transport=transport,
            resolver=resolver,
            client_factory=client_factory,
            conditional_headers={
                "if-none-match": latest_version.get("source_etag") or "",
                "if-modified-since": latest_version.get("source_last_modified") or "",
            },
        )
    except OutboundCollectionError as exc:
        http_status = int((exc.details or {}).get("http_status") or 0)
        if (
            exc.code == "OUTBOUND_HTTP_SOURCE_NOT_FOUND"
            and http_status in {404, 410}
            and latest_version.get("id")
            and _is_official_source(source)
        ):
            previous_hash = str(latest_version.get("content_hash") or "").lower()
            observation = record_source_refresh_observation(
                source_id,
                {
                    "request_method": method,
                    "http_status": http_status,
                    "outcome": "failed",
                    "source_version_id": latest_version.get("id") or "",
                    "content_hash": previous_hash,
                    "byte_size": int(latest_version.get("byte_size") or 0),
                    "fetch_url": source.get("canonical_url") or "",
                    "error_code": "OFFICIAL_SOURCE_REMOVED",
                    "error": {"code": "OFFICIAL_SOURCE_REMOVED"},
                    "metadata": {"conditional_request": bool(latest_version), "body_retained": False},
                    "detection_type": "removed",
                    "version_signal": {"previous_content_hash": previous_hash, "http_status": http_status},
                },
                user,
            )
            application = _apply_change_detection(
                detection_type="removed",
                observation=observation,
                reason_code=f"HTTP_{http_status}",
                source_version_id=str(latest_version.get("id") or ""),
            )
            _audit_fetch(
                "official_source_removed",
                details={
                    "code": "OFFICIAL_SOURCE_REMOVED",
                    "http_status": http_status,
                    "refresh_observation_id": observation.get("id"),
                    "change_action_id": observation.get("change_action_id"),
                    "action_status": application.get("action_status"),
                },
            )
            return {
                "source_id": source_id,
                "fetch": {"status_code": http_status, "not_modified": False, "bytes_read": 0},
                "version": None,
                "refresh": {
                    "outcome": "changed",
                    "collection_outcome": "failed",
                    "error_code": "OFFICIAL_SOURCE_REMOVED",
                    "content_hash": previous_hash,
                    "source_version_id": latest_version.get("id") or "",
                    "observation_id": observation.get("id"),
                    "change_action_id": observation.get("change_action_id"),
                    "detection_type": "removed",
                    "change_application": application,
                },
            }
        _audit_fetch(
            "fetch_failed",
            details={"code": exc.code, "status_code": exc.status_code, **dict(exc.details or {})},
        )
        raise SourceRegistryError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc

    fetch_metadata = result.as_dict(include_content=False)
    if result.not_modified:
        latest_hash = str(latest_version.get("content_hash") or "").lower()
        if not latest_version.get("id") or not _SHA256_RE.fullmatch(latest_hash):
            _audit_fetch(
                "fetch_failed",
                details={"code": "OUTBOUND_NOT_MODIFIED_WITHOUT_BASELINE", "status_code": result.status_code},
            )
            raise SourceRegistryError(
                "OUTBOUND_NOT_MODIFIED_WITHOUT_BASELINE",
                "Source returned 304 before an immutable source version existed",
                status_code=502,
            )
        redirected = bool(result.redirect_chain)
        detection_type = "replacement" if _is_material_replacement(source, result.final_url, had_baseline=True) else "none"
        observation = record_source_refresh_observation(
            source_id,
            {
                "request_method": method,
                "http_status": result.status_code,
                "outcome": "not_modified",
                "source_version_id": latest_version.get("id") or "",
                "content_hash": latest_hash,
                "byte_size": int(latest_version.get("byte_size") or 0),
                "source_etag": result.source_etag or latest_version.get("source_etag") or "",
                "source_last_modified": result.source_last_modified or latest_version.get("source_last_modified") or "",
                "fetch_url": result.final_url,
                "response_content_type": result.content_type,
                "metadata": {"conditional_request": True, "previous_source_version_id": latest_version.get("id") or ""},
                "detection_type": detection_type,
                "replacement_url": result.final_url if detection_type == "replacement" else "",
                "version_signal": {"previous_content_hash": latest_hash, "http_status": result.status_code},
            },
            user,
        )
        application = (
            _apply_change_detection(
                detection_type="replacement",
                observation=observation,
                reason_code="OFFICIAL_SOURCE_REPLACED",
                replacement_url=result.final_url,
                source_version_id=str(latest_version.get("id") or ""),
            )
            if detection_type == "replacement"
            else None
        )
        _audit_fetch(
            "fetch_not_modified",
            details={"method": method, **fetch_metadata, "content_hash": latest_hash},
            after={"status_code": result.status_code, "final_url": result.final_url},
        )
        return {
            "source_id": source_id,
            "fetch": fetch_metadata,
            "version": None,
            "refresh": {
                "outcome": "not_modified",
                "content_hash": latest_hash,
                "source_version_id": latest_version.get("id") or "",
                "observation_id": observation.get("id"),
                "change_action_id": observation.get("change_action_id"),
                "detection_type": detection_type,
                "replacement_url": result.final_url if detection_type == "replacement" else "",
                "change_application": application,
            },
        }
    # HEAD is an explicitly supported safety probe, but it has no document
    # bytes and therefore must not create a zero-byte source version.
    if method == "HEAD":
        _audit_fetch(
            "fetch_completed",
            details={"method": method, **fetch_metadata},
            after={"status_code": result.status_code, "final_url": result.final_url},
        )
        return {"source_id": source_id, "fetch": fetch_metadata, "version": None}

    policy = source.get("collection_policy") if isinstance(source.get("collection_policy"), dict) else {}
    version_payload = {
        "content": result.content,
        "fetched_at": _now(),
        "parser_name": str(policy.get("parser_name") or "html"),
        "parser_version": str(policy.get("parser_version") or "1.0.0"),
        "source_etag": result.source_etag,
        "source_last_modified": result.source_last_modified,
        "fetch_url": result.final_url,
        "response_content_type": result.content_type,
        "http_status": result.status_code,
        "raw_content_ref": "",
        "raw_content_storage": "hash_only_memory_boundary",
        "verification_method": "cat004_safe_outbound_http_v1",
        "metadata": {
            "redirect_chain": list(result.redirect_chain),
            "resolved_addresses": list(result.resolved_addresses),
            "bytes_read": result.bytes_read,
            "elapsed_ms": result.elapsed_ms,
        },
        "status": "fetched",
    }
    try:
        version = record_source_version(source_id, version_payload, user)
    except SourceRegistryError as exc:
        _audit_fetch(
            "fetch_failed",
            details={"code": exc.code, "status_code": exc.status_code},
        )
        raise
    observation_outcome = "changed" if not version.get("deduplicated") else "unchanged"
    redirected = bool(result.redirect_chain)
    material_replacement = _is_material_replacement(source, result.final_url, had_baseline=bool(latest_version.get("id")))
    detection_type = (
        "replacement"
        if material_replacement
        else (
            "version_updated"
            if _is_official_source(source) and bool(latest_version.get("id")) and observation_outcome == "changed"
            else "none"
        )
    )
    observation = record_source_refresh_observation(
        source_id,
        {
            "request_method": method,
            "http_status": result.status_code,
            "outcome": observation_outcome,
            "source_version_id": version.get("id") or "",
            "content_hash": version.get("content_hash") or "",
            "byte_size": int(version.get("byte_size") or result.bytes_read),
            "source_etag": result.source_etag,
            "source_last_modified": result.source_last_modified,
            "fetch_url": result.final_url,
            "response_content_type": result.content_type,
            "metadata": {"conditional_request": bool(latest_version), "deduplicated": bool(version.get("deduplicated"))},
            "detection_type": detection_type,
            "replacement_url": result.final_url if detection_type == "replacement" else "",
            "version_signal": {
                "previous_content_hash": str(latest_version.get("content_hash") or ""),
                "new_content_hash": str(version.get("content_hash") or ""),
                "redirected": redirected,
            },
        },
        user,
    )
    application = (
        _apply_change_detection(
            detection_type="replacement",
            observation=observation,
            reason_code="OFFICIAL_SOURCE_REPLACED",
            replacement_url=result.final_url,
            source_version_id=str(version.get("id") or ""),
        )
        if detection_type == "replacement"
        else None
    )
    version["refresh_observation_id"] = observation.get("id")
    version["detection_type"] = detection_type
    return {
        "source_id": source_id,
        "fetch": fetch_metadata,
        "version": version,
        "refresh": {
            "outcome": observation_outcome,
            "content_hash": version.get("content_hash") or "",
            "source_version_id": version.get("id") or "",
            "observation_id": observation.get("id"),
            "change_action_id": observation.get("change_action_id"),
            "detection_type": detection_type,
            "replacement_url": result.final_url if detection_type == "replacement" else "",
            "change_application": application,
        },
    }


def list_source_versions(source_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        source = _get_source_in_conn(conn, source_id, user)
        _authorize(user, "read", str(source.get("tenant_id") or ""))
        rows = conn.execute(
            "SELECT * FROM kb_source_version WHERE tenant_id = ? AND source_registry_id = ? ORDER BY fetched_at DESC, id",
            (source.get("tenant_id"), source_id),
        ).fetchall()
        return [_decode_version(row) for row in rows]
    finally:
        conn.close()
