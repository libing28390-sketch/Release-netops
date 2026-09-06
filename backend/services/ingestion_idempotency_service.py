"""Pure URL/content idempotency decisions for Knowledge Engine ingestion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from core.enum_compat import StrEnum


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class SourceContentDecision(StrEnum):
    NEW_VERSION = "new_version"
    REPLAY = "replay_same_url_same_content"
    CONFLICT = "identity_conflict"


@dataclass(frozen=True)
class SourceContentIdentity:
    tenant_id: str
    source_id: str
    canonical_url: str
    content_hash: str
    byte_size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "source_id": self.source_id,
            "canonical_url": self.canonical_url,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True)
class SourceContentIdempotency:
    decision: SourceContentDecision
    existing_version_id: str = ""
    same_content: bool = False
    reason: str = ""

    @property
    def replayed(self) -> bool:
        return self.decision is SourceContentDecision.REPLAY

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "existing_version_id": self.existing_version_id,
            "same_content": self.same_content,
            "replayed": self.replayed,
            "reason": self.reason,
        }


def _text(value: Any, *, field: str, maximum: int = 256, required: bool = True) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or CONTROL_RE.search(text):
        raise ValueError(f"IDEMPOTENCY_{field.upper()}_INVALID")
    return text


def _url(value: Any) -> str:
    url = _text(value, field="canonical_url", maximum=4096)
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("IDEMPOTENCY_URL_INVALID")
    return url


def build_url_idempotency_key(canonical_url: str) -> str:
    """Build the stable default request key without retaining URL contents."""
    return f"official-url:{hashlib.sha256(_url(canonical_url).encode('utf-8')).hexdigest()}"


def build_source_content_identity(
    *,
    tenant_id: str,
    source_id: str,
    canonical_url: str,
    content_hash: str,
    byte_size: int,
) -> SourceContentIdentity:
    digest = _text(content_hash, field="content_hash", maximum=64).lower()
    if not SHA256_RE.fullmatch(digest):
        raise ValueError("IDEMPOTENCY_CONTENT_HASH_INVALID")
    try:
        size = int(byte_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("IDEMPOTENCY_BYTE_SIZE_INVALID") from exc
    if size < 0:
        raise ValueError("IDEMPOTENCY_BYTE_SIZE_INVALID")
    return SourceContentIdentity(
        tenant_id=_text(tenant_id, field="tenant_id", maximum=128),
        source_id=_text(source_id, field="source_id", maximum=128),
        canonical_url=_url(canonical_url),
        content_hash=digest,
        byte_size=size,
    )


def classify_source_content(
    existing_version: Mapping[str, Any] | None,
    *,
    identity: SourceContentIdentity,
) -> SourceContentIdempotency:
    """Classify a version without comparing or retaining source bytes."""
    if existing_version is None:
        return SourceContentIdempotency(
            decision=SourceContentDecision.NEW_VERSION,
            reason="no_existing_version",
        )
    existing_tenant = str(existing_version.get("tenant_id") or "")
    existing_source = str(existing_version.get("source_registry_id") or existing_version.get("source_id") or "")
    existing_hash = str(existing_version.get("content_hash") or "").strip().lower()
    existing_url = str(existing_version.get("canonical_url") or identity.canonical_url)
    if existing_tenant and existing_tenant != identity.tenant_id:
        return SourceContentIdempotency(SourceContentDecision.CONFLICT, reason="tenant_scope_mismatch")
    if existing_source and existing_source != identity.source_id:
        return SourceContentIdempotency(SourceContentDecision.CONFLICT, reason="source_scope_mismatch")
    if existing_url != identity.canonical_url:
        return SourceContentIdempotency(SourceContentDecision.CONFLICT, reason="canonical_url_mismatch")
    if existing_hash == identity.content_hash:
        return SourceContentIdempotency(
            decision=SourceContentDecision.REPLAY,
            existing_version_id=str(existing_version.get("id") or ""),
            same_content=True,
            reason="same_canonical_url_and_content_hash",
        )
    return SourceContentIdempotency(
        decision=SourceContentDecision.NEW_VERSION,
        reason="same_source_new_content_hash",
    )


__all__ = [
    "SourceContentDecision",
    "SourceContentIdentity",
    "SourceContentIdempotency",
    "build_source_content_identity",
    "build_url_idempotency_key",
    "classify_source_content",
]
