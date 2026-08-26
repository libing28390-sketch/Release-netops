"""Server-side metadata preview and confirmation for Knowledge imports.

The legacy document endpoint remains available to older clients.  New import
flows can opt into this boundary by first requesting a preview and then
submitting the returned, short-lived HMAC token together with an explicit
confirmation flag.  The token binds the confirmation to the authenticated
tenant/user and to hashes of the exact document and metadata inputs; raw
document content is never placed in the token or logs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from typing import Any, Mapping

from core.config import settings
from ai.services.knowledge_metadata import (
    MetadataParseError,
    MetadataValidationError,
    merge_metadata,
    metadata_columns,
    validate_metadata,
)
from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source


_TOKEN_VERSION = "metadata-preview-v1"
_TOKEN_TTL_SECONDS = 15 * 60
_SENSITIVE_KEY_RE = re.compile(r"(?:secret|password|passwd|token|api[_-]?key|credential|authorization|cookie|private[_-]?key|tenant[_-]?id|user[_-]?id|acl|permission|identity)", re.I)
_RESERVED_METADATA_KEY_RE = re.compile(r"(?:^|_)(?:tenant|user|acl|permission|identity)(?:_|$)", re.I)


class MetadataConfirmationError(ValueError):
    """Stable, safe error returned by the preview/confirmation boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _actor(user: Mapping[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip() or "system"


def _tenant(user: Mapping[str, Any]) -> str:
    return str(user.get("tenant_id") or "tenant-default").strip() or "tenant-default"


def _secret() -> bytes:
    # Credential encryption key is already the application-owned secret used
    # for other security boundaries.  Keep the fallback deterministic for
    # local development; production deployments must override it in env.
    value = str(getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or getattr(settings, "SECRET_KEY", "") or "nexora-metadata-preview")
    return value.encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_metadata(value: Any, *, depth: int = 0) -> Any:
    """Return JSON-safe metadata without exposing credential-like fields."""

    if depth > 6:
        return "[truncated]"
    if isinstance(value, Mapping):
        return {
            str(key): _safe_metadata(item, depth=depth + 1)
            for key, item in value.items()
            if not _SENSITIVE_KEY_RE.search(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_metadata(item, depth=depth + 1) for item in list(value)[:100]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validate_source_metadata(metadata: Mapping[str, Any]) -> None:
    for key in metadata:
        key_text = str(key).strip()
        if _RESERVED_METADATA_KEY_RE.search(key_text):
            raise MetadataConfirmationError(
                "METADATA_AUTHORITY_FIELD_FORBIDDEN",
                "Metadata cannot contain tenant, identity, ACL, or permission fields",
                status_code=400,
            )
        if _SENSITIVE_KEY_RE.search(key_text):
            raise MetadataConfirmationError(
                "METADATA_SECRET_FIELD_FORBIDDEN",
                "Metadata cannot contain credential or secret fields",
                status_code=400,
            )
    try:
        json.dumps(dict(metadata), ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise MetadataConfirmationError("METADATA_INPUT_INVALID", "Metadata must be JSON serializable") from exc


def _normalized_inputs(
    *,
    name: str,
    content: str,
    vendor: str,
    platform: str | None,
    knowledge_source_type: str,
    source_trust_level: str,
    chunk_size: int,
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], str, list[str]]:
    """Parse and validate exactly the same semantic inputs as ingestion."""

    source_metadata = dict(metadata or {})
    _validate_source_metadata(source_metadata)
    raw_content = str(content or "")
    if not raw_content.strip():
        raise MetadataConfirmationError("METADATA_CONTENT_EMPTY", "Document content cannot be empty", status_code=400)
    try:
        parsed = parse_knowledge_source(raw_content, filename=name)
        directory_path = source_metadata.get("knowledge_directory_path") or source_metadata.get("source_relative_path")
        frontmatter = validate_metadata(
            parsed.metadata,
            directory_path=directory_path,
            name=name,
            allow_missing_required=parsed.metadata_parse_status == "missing",
        )
    except KnowledgeSourceParseError as exc:
        raise MetadataConfirmationError(
            "METADATA_SOURCE_PARSE_INVALID",
            exc.message,
            status_code=422,
            details=exc.details,
        ) from exc
    except MetadataParseError as exc:
        raise MetadataConfirmationError("METADATA_PARSE_INVALID", "Metadata Front Matter could not be parsed", status_code=422) from exc
    except MetadataValidationError as exc:
        # Required-field names and directory/category conflicts are safe to
        # show, but parser internals and raw document content are not.
        safe_message = str(exc)
        if len(safe_message) > 512:
            safe_message = safe_message[:512]
        raise MetadataConfirmationError("METADATA_VALIDATION_INVALID", safe_message, status_code=422) from exc

    merged = merge_metadata(frontmatter, source_metadata)
    warnings: list[str] = []
    warnings.extend(str(item) for item in parsed.warnings if str(item).strip())
    if parsed.metadata_parse_status == "missing":
        warnings.append("metadata_front_matter_missing_legacy_path")
        if vendor and str(vendor).strip().lower() != "all":
            merged.setdefault("vendor", vendor)
        if platform and str(platform).strip().lower() != "all":
            merged.setdefault("cli_platform", platform)
    if not str(merged.get("cli_platform") or "").strip():
        warnings.append("cli_platform_unresolved")
    merged.setdefault("status", "active")
    merged.setdefault("exclude_from_rag", False)
    normalized = {
        "name": str(name or "").strip(),
        "vendor": str(merged.get("vendor") or vendor or "all"),
        "platform": merged.get("cli_platform") if str(merged.get("cli_platform") or "").strip().lower() != "all" else None,
        "knowledge_source_type": str(knowledge_source_type or "user_document"),
        "source_trust_level": str(source_trust_level or "internal"),
        "chunk_size": int(chunk_size),
        "metadata_parse_status": parsed.metadata_parse_status,
        "format": parsed.format,
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "parse_warnings": list(parsed.warnings),
        "metadata": _safe_metadata(merged),
        "metadata_columns": _safe_metadata(metadata_columns(merged)),
        "content_sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
        "content_bytes": len(raw_content.encode("utf-8")),
        "body_characters": len(parsed.content.strip()),
    }
    digest_input = {
        "name": normalized["name"],
        "content_sha256": normalized["content_sha256"],
        "vendor": str(vendor or ""),
        "platform": platform,
        "knowledge_source_type": normalized["knowledge_source_type"],
        "source_trust_level": normalized["source_trust_level"],
        "chunk_size": normalized["chunk_size"],
        "metadata": source_metadata,
    }
    return normalized, digest_input, parsed.metadata_parse_status, warnings


def _encode_claims(claims: Mapping[str, Any]) -> str:
    body = _b64(json.dumps(dict(claims), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def _decode_claims(token: str) -> dict[str, Any]:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        claims = json.loads(_unb64(body).decode("utf-8"))
        if not isinstance(claims, dict):
            raise ValueError("claims")
        return claims
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise MetadataConfirmationError("METADATA_CONFIRMATION_INVALID", "Metadata confirmation token is invalid", status_code=409) from exc


def preview_document_metadata(
    *,
    user: Mapping[str, Any],
    name: str,
    content: str,
    vendor: str = "all",
    platform: str | None = None,
    knowledge_source_type: str = "user_document",
    source_trust_level: str = "internal",
    chunk_size: int = 800,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a redacted preview and a short-lived confirmation token."""

    normalized, digest_input, parse_status, warnings = _normalized_inputs(
        name=name,
        content=content,
        vendor=vendor,
        platform=platform,
        knowledge_source_type=knowledge_source_type,
        source_trust_level=source_trust_level,
        chunk_size=chunk_size,
        metadata=metadata,
    )
    now = int(time.time())
    preview_id = f"mdp_{uuid.uuid4().hex[:16]}"
    claims = {
        "v": _TOKEN_VERSION,
        "preview_id": preview_id,
        "tenant_id": _tenant(user),
        "actor_id": _actor(user),
        "digest": _json_digest(digest_input),
        "issued_at": now,
        "expires_at": now + _TOKEN_TTL_SECONDS,
    }
    return {
        "preview_id": preview_id,
        "confirmation_token": _encode_claims(claims),
        "expires_at": claims["expires_at"],
        "metadata_parse_status": parse_status,
        "normalized": normalized,
        "warnings": warnings,
        "requires_confirmation": True,
    }


def validate_metadata_confirmation(
    *,
    user: Mapping[str, Any],
    token: str | None,
    confirmed: bool,
    name: str,
    content: str,
    vendor: str = "all",
    platform: str | None = None,
    knowledge_source_type: str = "user_document",
    source_trust_level: str = "internal",
    chunk_size: int = 800,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify explicit human confirmation against the exact import input."""

    if not token or not confirmed:
        raise MetadataConfirmationError(
            "METADATA_CONFIRMATION_REQUIRED",
            "Review the metadata preview and explicitly confirm before importing",
            status_code=400,
        )
    claims = _decode_claims(token)
    now = int(time.time())
    if claims.get("v") != _TOKEN_VERSION or int(claims.get("expires_at") or 0) < now:
        raise MetadataConfirmationError("METADATA_CONFIRMATION_EXPIRED", "Metadata confirmation has expired; request a new preview", status_code=409)
    if claims.get("tenant_id") != _tenant(user) or claims.get("actor_id") != _actor(user):
        raise MetadataConfirmationError("METADATA_CONFIRMATION_SCOPE_MISMATCH", "Metadata confirmation belongs to another user or tenant", status_code=403)
    _normalized, digest_input, _status, _warnings = _normalized_inputs(
        name=name,
        content=content,
        vendor=vendor,
        platform=platform,
        knowledge_source_type=knowledge_source_type,
        source_trust_level=source_trust_level,
        chunk_size=chunk_size,
        metadata=metadata,
    )
    if not hmac.compare_digest(str(claims.get("digest") or ""), _json_digest(digest_input)):
        raise MetadataConfirmationError("METADATA_CONFIRMATION_STALE", "The document or metadata changed after preview; request a new preview", status_code=409)
    return {"preview_id": str(claims.get("preview_id") or ""), "confirmed_at": now}


__all__ = ["MetadataConfirmationError", "preview_document_metadata", "validate_metadata_confirmation"]
