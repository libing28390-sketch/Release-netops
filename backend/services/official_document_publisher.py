"""Publish one fetched official source into the local RAG projection.

The source registry deliberately stores only immutable source facts.  This
module is the trusted continuation boundary that receives the in-memory body
from ``collect_source`` and turns it into a cleaned, chunked, embedded local
document.  It never returns the source body to an API caller.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from ai.services.knowledge_metadata import canonical_feature, directory_metadata_for_document
from ai.services.knowledge_service import knowledge_service
from database import get_db_connection
from services.document_content_cleaning import CleanedDocument, parse_and_clean_document


class OfficialDocumentPublicationError(ValueError):
    """Safe publication error for the ingestion control plane."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


_FEATURES = (
    ("ospf", "routing"),
    ("bgp", "routing"),
    ("isis", "routing"),
    ("vrrp", "reliability"),
    ("stp", "switching"),
    ("mstp", "switching"),
    ("vlan", "switching"),
    ("vxlan", "overlay"),
    ("evpn", "overlay"),
    ("lacp", "switching"),
    ("port_security", "security"),
    ("snmp", "management"),
)


def _filename_for(url: str, content_type: str) -> str:
    suffix = ".html"
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized == "application/pdf":
        suffix = ".pdf"
    elif normalized in {"text/plain"}:
        suffix = ".txt"
    elif normalized in {"text/markdown"}:
        suffix = ".md"
    path = urlsplit(url).path.rsplit("/", 1)[-1]
    if "." in path and len(path.rsplit(".", 1)[-1]) <= 8:
        suffix = "." + path.rsplit(".", 1)[-1].lower()
    return f"official-source{suffix}"


def _feature_for(*values: Any) -> tuple[str, str]:
    """Infer a feature from source identity fields, never from full body text.

    A vendor command-reference page commonly contains commands for many
    unrelated features.  Looking through the first part of that page and
    assigning the first keyword found made the whole document appear to be a
    VLAN/OSPF/etc. document.  Callers should pass only reviewed identity
    fields such as title, description, source name, and URL.
    """
    haystack = " ".join(str(value or "") for value in values).lower()
    for feature, domain in _FEATURES:
        if re.search(rf"(?<![a-z0-9]){re.escape(feature)}(?![a-z0-9])", haystack):
            return feature, domain
    return "", "general"


def _feature_domain(feature: str) -> str:
    return dict(_FEATURES).get(str(feature or "").strip().lower(), "general")


def _category_for(source_kind: str, feature: str) -> str:
    if source_kind == "troubleshooting_guide":
        return "troubleshooting"
    if source_kind in {"configuration_guide", "command_reference"}:
        return "configuration" if source_kind == "configuration_guide" else "command"
    if source_kind == "release_note":
        return "troubleshooting"
    if feature:
        return "configuration"
    return "hardware"


def _decode_source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    value = source.get("metadata")
    return dict(value) if isinstance(value, dict) else {}


def _existing_document(tenant_id: str, content_hash: str, *, exclude_document_id: str = "") -> dict[str, Any] | None:
    params: list[Any] = [tenant_id, content_hash]
    exclusion = ""
    if exclude_document_id:
        exclusion = " AND id <> ?"
        params.append(exclude_document_id)
    with get_db_connection() as conn:
        row = conn.execute(
            f"""
            SELECT id, document_id, name, content_hash, knowledge_source_type
            FROM ai_document
            WHERE tenant_id = ? AND knowledge_source_type = 'official_url'
              AND content_hash = ?
              {exclusion}
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    if not row:
        return None
    return {
        "storage_document_id": str(row[0] or ""),
        "document_id": str(row[1] or row[0] or ""),
        "name": str(row[2] or ""),
        "content_hash": str(row[3] or ""),
        "knowledge_source_type": str(row[4] or "official_url"),
    }


def publish_official_document(
    *,
    user: dict[str, Any],
    source: dict[str, Any],
    source_version: dict[str, Any],
    raw_content: bytes,
    content_type: str,
    source_kind: str,
    payload: dict[str, Any] | None = None,
    cleaned: CleanedDocument | None = None,
) -> dict[str, Any]:
    """Parse, clean, index, and return bounded publication facts."""

    if not isinstance(raw_content, bytes) or not raw_content:
        raise OfficialDocumentPublicationError("PUBLISH_CONTENT_EMPTY", "Official source content is empty")
    payload = dict(payload or {})
    canonical_url = str(source.get("canonical_url") or payload.get("url") or "").strip()
    if not canonical_url:
        raise OfficialDocumentPublicationError("PUBLISH_SOURCE_INVALID", "Official source URL is missing")
    cleaned_document = cleaned or parse_and_clean_document(
        raw_content,
        filename=_filename_for(canonical_url, content_type),
        content_type=content_type,
    )
    normalized_content = str(cleaned_document.text or "").strip()
    if not normalized_content:
        raise OfficialDocumentPublicationError("PUBLISH_CONTENT_EMPTY", "Official source has no searchable text")

    source_meta = _decode_source_metadata(source)
    version_scope = source_meta.get("version_scope") if isinstance(source_meta.get("version_scope"), dict) else {}
    vendor = str(payload.get("vendor") or source_meta.get("vendor") or "").strip()
    product_family = str(payload.get("product_family") or source_meta.get("product_family") or "").strip()
    if not vendor or not product_family:
        raise OfficialDocumentPublicationError("PUBLISH_METADATA_INVALID", "Official source vendor and product family are required")
    explicit_feature = str(payload.get("feature") or source_meta.get("feature") or "").strip()
    if explicit_feature:
        feature = canonical_feature(explicit_feature)
        feature_domain = str(
            payload.get("feature_domain")
            or source_meta.get("feature_domain")
            or _feature_domain(feature)
        ).strip() or _feature_domain(feature)
        feature_source = "explicit"
    else:
        # Broad source bodies are intentionally excluded.  The title/URL
        # binding is still useful for a reviewed feature-specific page such as
        # an OSPF command reference.
        feature, feature_domain = _feature_for(
            payload.get("name"),
            payload.get("description"),
            source.get("name"),
            canonical_url,
        )
        feature_source = "title_or_url" if feature else "unclassified"
    category = _category_for(source_kind, feature)
    document_id = f"official-{str(source_version.get('id') or hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()[:24])}"
    content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    tenant_id = str(source.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    # The V1 source identity is intentionally not treated as a published
    # searchable document.  Exclude it from the content replay lookup so an
    # explicit publish creates the local ai_document/ai_document_chunk
    # projection exactly once.
    replay = _existing_document(
        tenant_id,
        content_hash,
        exclude_document_id=str(source.get("source_document_id") or ""),
    )
    if replay:
        return {
            "published": True,
            "replayed": True,
            "document_id": replay["document_id"],
            "storage_document_id": replay["storage_document_id"],
            "name": replay["name"],
            "chunk_count": 0,
            "content_hash": content_hash,
            "parser_name": cleaned_document.parser_name,
            "parser_version": cleaned_document.parser_version,
            "cleaner_name": cleaned_document.cleaning_name,
            "cleaner_version": cleaned_document.cleaning_version,
        }

    primary_version = str(version_scope.get("primary") or payload.get("version") or "").strip()
    metadata: dict[str, Any] = {
        "schema_version": "1.0",
        "document_id": document_id,
        "title": str(payload.get("name") or source.get("name") or canonical_url),
        "vendor": vendor,
        "product_type": "network_switch",
        "document_category": category,
        "source_type": "official_url",
        "source_kind": source_kind,
        "official_only": True,
        "status": "active",
        "product_family": product_family,
        "product_series": str(payload.get("product_series") or source_meta.get("product_series") or product_family),
        "product_model": str(payload.get("product_model") or source_meta.get("product_model") or ""),
        "os_family": str(source_meta.get("os_family") or payload.get("os_family") or ""),
        "os_generation": str(source_meta.get("os_generation") or ""),
        "software_train": primary_version,
        "software_release": primary_version,
        "cli_platform": str(source_meta.get("platform_code") or payload.get("platform_code") or ""),
        "feature_domain": feature_domain,
        "feature": feature,
        "feature_source": feature_source,
        "risk_level": "low",
        "verification_level": "official",
        "rag_priority": 100,
        "source_url": canonical_url,
        "canonical_url": canonical_url,
        "official_reference": canonical_url,
        "source_registry_id": str(source.get("id") or ""),
        "source_version_id": str(source_version.get("id") or ""),
        "source_content_hash": str(source_version.get("content_hash") or ""),
        "source_version": primary_version,
        "parser_name": cleaned_document.parser_name,
        "parser_version": cleaned_document.parser_version,
        "cleaner_name": cleaned_document.cleaning_name,
        "cleaner_version": cleaned_document.cleaning_version,
        "content_cleaning": cleaned_document.metadata.get("content_cleaning", {}),
    }
    metadata.update({
        key: value
        for key, value in source_meta.items()
        if key in {"product_series", "product_model", "os_family", "os_generation", "platform_code", "feature_domain", "feature"}
        and value not in (None, "")
    })
    metadata["cli_platform"] = str(metadata.get("cli_platform") or "")
    metadata["product_series"] = str(metadata.get("product_series") or product_family)
    metadata["document_category"] = category
    metadata["source_type"] = "official_url"
    metadata["official_only"] = True
    metadata["status"] = "active"
    # Source metadata may contain legacy hints.  The reviewed/identity-based
    # decision above is the publication authority and must win the merge.
    metadata["feature_domain"] = feature_domain
    metadata["feature"] = feature
    metadata["feature_source"] = feature_source
    metadata.update(directory_metadata_for_document(category, vendor))

    kb = knowledge_service.get_or_create_default_knowledge_base(tenant_id=tenant_id, created_by=str(user.get("id") or user.get("username") or "system"))
    result = knowledge_service.add_document_and_chunk(
        knowledge_base_id=str(kb["id"]),
        name=str(metadata["title"]),
        content=normalized_content,
        vendor=vendor,
        platform=metadata.get("cli_platform") or None,
        knowledge_source_type="official_url",
        chunk_size=800,
        tenant_id=tenant_id,
        source_trust_level="official",
        metadata=metadata,
        source=canonical_url,
    )
    # Persist the searchable publication as a V1 revision after the formal
    # document/chunk transaction succeeds.  The source manifest remains the
    # immutable fetch fact; this row records the normalized text actually used
    # by the V1 retriever.
    try:
        from services.knowledge_v1_source_service import record_document_revision

        original_for_revision: bytes | None = None
        try:
            raw_content.decode("utf-8")
            original_for_revision = raw_content
        except UnicodeDecodeError:
            # Binary documents keep their source hash and fetch metadata; the
            # normalized searchable representation is still fully recorded.
            original_for_revision = None
        record_document_revision(
            str(result.get("document_id") or ""),
            source,
            source_version,
            user,
            metadata=metadata,
            original_content=original_for_revision,
            normalized_content=normalized_content,
            cleaner_name=cleaned_document.cleaning_name,
            cleaner_version=cleaned_document.cleaning_version,
            document_kind=(
                "command_reference"
                if source_kind == "command_reference"
                else ("troubleshooting" if source_kind == "troubleshooting_guide" else "official_manual")
            ),
        )
    except Exception as exc:
        raise OfficialDocumentPublicationError("PUBLISH_REVISION_FAILED", "V1 document revision could not be persisted") from exc
    return {
        "published": True,
        "replayed": False,
        "document_id": str(result.get("document_id") or document_id),
        "storage_document_id": str(result.get("document_id") or ""),
        "name": str(metadata["title"]),
        "chunk_count": int(result.get("chunk_count") or 0),
        "content_hash": content_hash,
        "parser_name": cleaned_document.parser_name,
        "parser_version": cleaned_document.parser_version,
        "cleaner_name": cleaned_document.cleaning_name,
        "cleaner_version": cleaned_document.cleaning_version,
    }


__all__ = ["OfficialDocumentPublicationError", "publish_official_document"]
