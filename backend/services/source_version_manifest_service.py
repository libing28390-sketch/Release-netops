"""ING-009 immutable source-version manifest contract.

The source registry already owns the database write, but every collection path
must produce the same server-owned provenance record.  This module is pure and
side-effect free so the write boundary can validate and embed the manifest in
`metadata_json` without retaining source bytes or trusting caller metadata.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit


MANIFEST_VERSION = "1.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class SourceVersionManifestError(ValueError):
    """Stable validation error for the ING-009 manifest boundary."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _bounded_text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or _CONTROL_RE.search(text):
        raise SourceVersionManifestError("MANIFEST_FIELD_INVALID", f"{field} is invalid")
    return text


def _validate_timestamp(value: Any) -> str:
    timestamp = _bounded_text(value, field="fetched_at", maximum=128, required=True)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceVersionManifestError("MANIFEST_CAPTURE_TIME_INVALID", "fetched_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SourceVersionManifestError("MANIFEST_CAPTURE_TIME_INVALID", "fetched_at must include a timezone")
    return timestamp


def _validate_url(value: Any, *, field: str) -> str:
    url = _bounded_text(value, field=field, maximum=4096, required=True)
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise SourceVersionManifestError("MANIFEST_SOURCE_URL_INVALID", f"{field} must be an HTTPS URL without userinfo or fragment")
    return url


def build_source_version_manifest(
    source: Mapping[str, Any],
    *,
    content_hash: str,
    byte_size: int,
    fetched_at: str,
    parser_name: str,
    parser_version: str,
    fetch_url: str,
    source_etag: str = "",
    source_last_modified: str = "",
    response_content_type: str = "",
    http_status: int | None = None,
    raw_content_ref: str = "",
    raw_content_storage: str = "",
    verification_method: str = "",
    status: str = "fetched",
) -> dict[str, Any]:
    """Build a server-owned, redacted immutable manifest.

    The returned object contains provenance facts only.  It never contains the
    downloaded body, a local filesystem path, authorization material or a
    caller-provided arbitrary metadata object.
    """

    source_id = _bounded_text(source.get("id"), field="source_registry_id", maximum=128, required=True)
    tenant_id = _bounded_text(source.get("tenant_id"), field="tenant_id", maximum=128, required=True)
    canonical_url = _validate_url(source.get("canonical_url"), field="source.canonical_url")
    normalized_fetch_url = _validate_url(fetch_url or canonical_url, field="fetch_url")
    digest = _bounded_text(content_hash, field="content_hash", maximum=64, required=True).lower()
    if not SHA256_RE.fullmatch(digest):
        raise SourceVersionManifestError("MANIFEST_HASH_INVALID", "content_hash must be a lowercase SHA-256 digest")
    try:
        size = int(byte_size)
    except (TypeError, ValueError) as exc:
        raise SourceVersionManifestError("MANIFEST_BYTE_SIZE_INVALID", "byte_size must be a non-negative integer") from exc
    if size < 0:
        raise SourceVersionManifestError("MANIFEST_BYTE_SIZE_INVALID", "byte_size must be a non-negative integer")
    captured = _validate_timestamp(fetched_at)
    parser = _bounded_text(parser_name, field="parser_name", maximum=128, required=True)
    version = _bounded_text(parser_version, field="parser_version", maximum=64, required=True)
    etag = _bounded_text(source_etag, field="source_etag", maximum=512)
    last_modified = _bounded_text(source_last_modified, field="source_last_modified", maximum=256)
    content_type = _bounded_text(response_content_type, field="response_content_type", maximum=256)
    if http_status is not None:
        try:
            status_code = int(http_status)
        except (TypeError, ValueError) as exc:
            raise SourceVersionManifestError("MANIFEST_HTTP_STATUS_INVALID", "http_status must be between 100 and 599") from exc
        if not 100 <= status_code <= 599:
            raise SourceVersionManifestError("MANIFEST_HTTP_STATUS_INVALID", "http_status must be between 100 and 599")
    else:
        status_code = None
    raw_ref = _bounded_text(raw_content_ref, field="raw_content_ref", maximum=2048)
    if raw_ref and ("\\" in raw_ref or _CONTROL_RE.search(raw_ref) or raw_ref.startswith(("/", "\\", "file:", "C:", "D:"))):
        raise SourceVersionManifestError("MANIFEST_RAW_REFERENCE_FORBIDDEN", "raw_content_ref may not be a filesystem path")
    storage = _bounded_text(raw_content_storage, field="raw_content_storage", maximum=128)
    if not storage:
        storage = "hash_only_memory_boundary"
    method = _bounded_text(verification_method, field="verification_method", maximum=128)
    lifecycle = _bounded_text(status, field="status", maximum=32, required=True).lower()
    if lifecycle not in {"draft", "fetched", "verified", "failed", "quarantined"}:
        raise SourceVersionManifestError("MANIFEST_STATUS_INVALID", "source version status is not allowed")
    return {
        "manifest_version": MANIFEST_VERSION,
        "source": {
            "registry_id": source_id,
            "tenant_id": tenant_id,
            "canonical_url": canonical_url,
        },
        "capture": {
            "fetched_at": captured,
            "content_hash": digest,
            "byte_size": size,
        },
        "http": {
            "fetch_url": normalized_fetch_url,
            "status": status_code,
            "content_type": content_type,
            "etag": etag,
            "last_modified": last_modified,
        },
        "parser": {
            "name": parser,
            "version": version,
        },
        "raw_content": {
            "reference": raw_ref,
            "storage": storage,
        },
        "verification_method": method,
        "status": lifecycle,
    }


def validate_source_version_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a persisted manifest without returning any source body."""

    if not isinstance(manifest, Mapping):
        raise SourceVersionManifestError("MANIFEST_OBJECT_REQUIRED", "source manifest must be an object")
    required = {"manifest_version", "source", "capture", "http", "parser", "raw_content", "status"}
    missing = sorted(required - set(manifest))
    if missing:
        raise SourceVersionManifestError("MANIFEST_FIELD_MISSING", "source manifest is missing required fields", details={"fields": missing})
    source = manifest.get("source")
    capture = manifest.get("capture")
    http = manifest.get("http")
    parser = manifest.get("parser")
    raw = manifest.get("raw_content")
    if not all(isinstance(item, Mapping) for item in (source, capture, http, parser, raw)):
        raise SourceVersionManifestError("MANIFEST_NESTED_OBJECT_INVALID", "source manifest nested fields must be objects")
    source_for_rebuild = {
        "id": source.get("registry_id"),
        "tenant_id": source.get("tenant_id"),
        "canonical_url": source.get("canonical_url"),
    }
    rebuilt = build_source_version_manifest(
        source_for_rebuild,
        content_hash=capture.get("content_hash"),
        byte_size=capture.get("byte_size"),
        fetched_at=capture.get("fetched_at"),
        parser_name=parser.get("name"),
        parser_version=parser.get("version"),
        fetch_url=http.get("fetch_url"),
        source_etag=http.get("etag"),
        source_last_modified=http.get("last_modified"),
        response_content_type=http.get("content_type"),
        http_status=http.get("status"),
        raw_content_ref=raw.get("reference"),
        raw_content_storage=raw.get("storage"),
        verification_method=manifest.get("verification_method"),
        status=manifest.get("status"),
    )
    if str(manifest.get("manifest_version")) != MANIFEST_VERSION:
        raise SourceVersionManifestError("MANIFEST_VERSION_UNSUPPORTED", "source manifest version is unsupported")
    return copy.deepcopy(rebuilt)


__all__ = [
    "MANIFEST_VERSION",
    "SourceVersionManifestError",
    "build_source_version_manifest",
    "validate_source_version_manifest",
]
