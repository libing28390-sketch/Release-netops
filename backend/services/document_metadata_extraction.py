"""ING-010 deterministic document Metadata extraction and validation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

from ai.security.classification import DataLevel, classify
from core.enum_compat import StrEnum
from ai.services.knowledge_metadata import (
    DIRECTORY_VENDOR_MAP,
    HIGH_FREQUENCY_METADATA_FIELDS,
    REQUIRED_METADATA_FIELDS,
    ROOT_CATEGORY_MAP,
    canonical_vendor,
    metadata_columns,
)
from services.document_content_cleaning import CleanedDocument
from services.document_security_scan import DocumentSecurityScanResult, SecurityDecision


EXTRACTOR_NAME = "nexora-document-metadata"
EXTRACTOR_VERSION = "1.0.0"
METADATA_CONTRACT_VERSION = "1.0"
UNKNOWN_VALUE = "UNKNOWN"
MAX_METADATA_BYTES = 64 * 1024
MAX_METADATA_FIELDS = 128
MAX_METADATA_DEPTH = 4
MAX_METADATA_TEXT = 4096


class DocumentMetadataError(ValueError):
    """Stable redacted error for the ING-010 Metadata boundary."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class MetadataStatus(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"
    QUARANTINED = "quarantined"


class MetadataDecision(StrEnum):
    PROCEED = "proceed"
    REVIEW = "review"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class MetadataIssue:
    code: str
    field: str
    severity: str
    source: str
    value_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "severity": self.severity,
            "source": self.source,
            "value_hash": self.value_hash,
        }


@dataclass(frozen=True)
class DocumentMetadataResult:
    format: str
    status: MetadataStatus
    decision: MetadataDecision
    entity_resolution_allowed: bool
    publication_allowed: bool
    metadata: dict[str, Any]
    indexed_columns: dict[str, Any]
    field_sources: dict[str, str]
    unknown_fields: dict[str, str]
    unresolved_values: dict[str, str]
    issues: tuple[MetadataIssue, ...]
    metadata_hash: str
    document_hash: str
    provenance: dict[str, Any]
    extractor_name: str = EXTRACTOR_NAME
    extractor_version: str = EXTRACTOR_VERSION
    contract_version: str = METADATA_CONTRACT_VERSION
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "status": self.status.value,
            "decision": self.decision.value,
            "entity_resolution_allowed": self.entity_resolution_allowed,
            "publication_allowed": self.publication_allowed,
            "metadata": copy.deepcopy(self.metadata),
            "indexed_columns": copy.deepcopy(self.indexed_columns),
            "field_sources": dict(self.field_sources),
            "unknown_fields": dict(self.unknown_fields),
            "unresolved_values": dict(self.unresolved_values),
            "issues": [item.as_dict() for item in self.issues],
            "metadata_hash": self.metadata_hash,
            "document_hash": self.document_hash,
            "provenance": copy.deepcopy(self.provenance),
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
            "contract_version": self.contract_version,
            "warnings": list(self.warnings),
        }


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UNKNOWN_TOKENS = frozenset({"", "unknown", "n/a", "na", "none", "null", "unset", "-", "未知", "未指定", "不明"})
_KNOWN_VENDORS = frozenset({"Huawei", "Cisco", "H3C", "Ruijie", "all"})
_DOCUMENT_CATEGORIES = frozenset({
    "hardware",
    "command",
    "configuration",
    "cli_output",
    "troubleshooting",
    "example",
    "release_note",
    "reference",
    "guide",
    "sop",
    "product",
    "other",
})
_CATEGORY_ALIASES = {
    "commands": "command",
    "config": "configuration",
    "configs": "configuration",
    "cli-output": "cli_output",
    "cli output": "cli_output",
    "trouble_shooting": "troubleshooting",
    "release notes": "release_note",
}
_SOURCE_TYPES = frozenset({
    "official",
    "official_url",
    "official_file",
    "product_page",
    "configuration_guide",
    "command_reference",
    "release_note",
    "product_support",
    "enterprise",
    "internal",
    "internal_sop",
    "local_file",
    "user_document",
})
_SOURCE_TYPE_ALIASES = {
    "enterprise_sop": "internal_sop",
    "sop": "internal_sop",
    "official_document": "official",
}
_LIFECYCLE_STATUSES = frozenset({"draft", "active", "published", "quarantined", "superseded", "disabled", "archived", "deprecated"})
_LIST_FIELDS = frozenset({"product_models", "applicable_product_models", "tags", "keywords"})
_LOWER_FIELDS = frozenset({
    "document_category",
    "source_type",
    "status",
    "product_type",
    "cli_platform",
    "feature_domain",
    "feature",
    "subfeature",
    "risk_level",
    "verification_level",
    "language",
})
_APPLICABILITY_FIELDS = (
    "product_family",
    "product_series",
    "product_model",
    "os_family",
    "os_generation",
    "software_train",
    "software_release",
    "cli_platform",
)
_HIGH_RISK_CATEGORIES = frozenset({"command", "configuration", "cli_output", "troubleshooting"})
_OPERATIONAL_METADATA_FIELDS = frozenset({"content_cleaning", "page_count"})
_SERVER_OWNED_FIELDS = frozenset({
    "tenant_id",
    "workspace_id",
    "user_id",
    "created_by",
    "updated_by",
    "acl",
    "acl_json",
    "permissions",
    "roles",
    "authorization",
    "api_key",
    "password",
    "secret",
    "token",
    "private_key",
    "raw_content",
    "original_content",
    "content",
    "body",
})
_SOURCE_CONFLICT_FIELDS = frozenset({"vendor", "document_category", "source_type", "official_only"})
_SOURCE_OWNED_FIELDS = frozenset({"source_id", "source_version_id", "source_url", "source_trust_level", "classification", "exclude_from_rag"})
_KNOWN_FIELDS = frozenset(
    set(REQUIRED_METADATA_FIELDS)
    | set(HIGH_FREQUENCY_METADATA_FIELDS)
    | set(_LIST_FIELDS)
    | {
        "document_type",
        "description",
        "language",
        "keywords",
        "source_url",
        "source_id",
        "source_version_id",
        "source_trust_level",
        "classification",
        "published_at",
        "updated_at",
        "author",
        "technical_series",
        "exclude_from_rag",
    }
)


def _value_hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _document_hash(document: CleanedDocument) -> str:
    return hashlib.sha256(str(document.text or "").encode("utf-8", errors="replace")).hexdigest()


def _normalize_key(value: Any, *, source: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[-\s]+", "_", text)
    if not _KEY_RE.fullmatch(text):
        raise DocumentMetadataError("METADATA_KEY_INVALID", "Metadata key is invalid", details={"source": source})
    return text


def _normalize_text(value: Any, *, field_name: str, maximum: int = MAX_METADATA_TEXT) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > maximum or _CONTROL_RE.search(text):
        raise DocumentMetadataError("METADATA_TEXT_INVALID", "Metadata text is invalid", details={"field": field_name})
    return text


def _normalize_json_value(value: Any, *, field_name: str, depth: int = 0) -> Any:
    if depth > MAX_METADATA_DEPTH:
        raise DocumentMetadataError("METADATA_DEPTH_EXCEEDED", "Metadata nesting is too deep", details={"field": field_name})
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DocumentMetadataError("METADATA_VALUE_INVALID", "Metadata number is invalid", details={"field": field_name})
        return value
    if isinstance(value, str):
        return _normalize_text(value, field_name=field_name)
    if isinstance(value, (list, tuple, set)):
        if len(value) > MAX_METADATA_FIELDS:
            raise DocumentMetadataError("METADATA_COLLECTION_TOO_LARGE", "Metadata collection is too large", details={"field": field_name})
        items = sorted(value, key=lambda item: str(item)) if isinstance(value, set) else value
        return [_normalize_json_value(item, field_name=field_name, depth=depth + 1) for item in items]
    if isinstance(value, Mapping):
        if len(value) > MAX_METADATA_FIELDS:
            raise DocumentMetadataError("METADATA_COLLECTION_TOO_LARGE", "Metadata collection is too large", details={"field": field_name})
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _normalize_key(key, source=field_name)
            if normalized_key in result:
                raise DocumentMetadataError("METADATA_DUPLICATE_KEY", "Metadata keys collide after normalization", details={"field": field_name})
            if normalized_key in _SERVER_OWNED_FIELDS:
                raise DocumentMetadataError("METADATA_RESERVED_FIELD", "Server-owned Metadata field is forbidden", details={"field": normalized_key})
            result[normalized_key] = _normalize_json_value(item, field_name=normalized_key, depth=depth + 1)
        return result
    raise DocumentMetadataError("METADATA_VALUE_INVALID", "Metadata value type is invalid", details={"field": field_name})


def _normalize_mapping(value: Mapping[str, Any] | None, *, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DocumentMetadataError("METADATA_MAPPING_REQUIRED", "Metadata must be an object", details={"source": source})
    if len(value) > MAX_METADATA_FIELDS:
        raise DocumentMetadataError("METADATA_FIELD_LIMIT", "Metadata contains too many fields", details={"source": source})
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_key(raw_key, source=source)
        if key in result:
            raise DocumentMetadataError("METADATA_DUPLICATE_KEY", "Metadata keys collide after normalization", details={"source": source})
        if key in _SERVER_OWNED_FIELDS:
            raise DocumentMetadataError("METADATA_RESERVED_FIELD", "Server-owned Metadata field is forbidden", details={"field": key, "source": source})
        result[key] = _normalize_json_value(raw_value, field_name=key)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise DocumentMetadataError("METADATA_TOO_LARGE", "Metadata exceeds the size limit", details={"source": source})
    return result


def _normalize_bool(value: Any, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = _normalize_text(value, field_name=field_name, maximum=16).lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    if text in _UNKNOWN_TOKENS:
        return None
    raise DocumentMetadataError("METADATA_BOOLEAN_INVALID", "Metadata boolean is invalid", details={"field": field_name})


def _require_scalar(value: Any, *, field_name: str) -> Any:
    if isinstance(value, (Mapping, list, tuple, set)):
        raise DocumentMetadataError("METADATA_VALUE_INVALID", "Metadata field must be scalar", details={"field": field_name})
    return value


def _normalize_list(value: Any, *, field_name: str) -> list[str]:
    if isinstance(value, Mapping):
        raise DocumentMetadataError("METADATA_VALUE_INVALID", "Metadata list field is invalid", details={"field": field_name})
    if isinstance(value, set):
        items = sorted(value, key=lambda item: str(item))
    else:
        items = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        _require_scalar(item, field_name=field_name)
        text = _normalize_text(item, field_name=field_name, maximum=512)
        if not text or text.lower() in _UNKNOWN_TOKENS:
            continue
        if text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _canonical_enum(value: Any, *, field_name: str, aliases: Mapping[str, str], allowed: frozenset[str]) -> tuple[str, str | None]:
    text = _normalize_text(value, field_name=field_name, maximum=128).lower()
    if text in _UNKNOWN_TOKENS:
        return UNKNOWN_VALUE, "explicit_unknown"
    canonical = aliases.get(text, text.replace("-", "_").replace(" ", "_"))
    if canonical not in allowed:
        return UNKNOWN_VALUE, "unrecognized_value"
    return canonical, None


def _directory_hints(directory_path: str) -> tuple[str | None, str | None]:
    parts = [part.strip().lower() for part in str(directory_path or "").replace("\\", "/").split("/") if part.strip()]
    if parts and parts[0] == "kb_import":
        parts = parts[1:]
    if not parts:
        return None, None
    return ROOT_CATEGORY_MAP.get(parts[0]), DIRECTORY_VENDOR_MAP.get(parts[1]) if len(parts) > 1 else None


def _fallback_title(document: CleanedDocument, filename: str) -> tuple[str, str]:
    for block in document.blocks:
        if str(block.block_type or "").lower() == "heading" and str(block.text or "").strip():
            return _normalize_text(block.text, field_name="title", maximum=512), "document_heading"
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    title = _normalize_text(stem, field_name="title", maximum=512)
    return (title, "filename") if title else (UNKNOWN_VALUE, "default_unknown")


def _security_check(metadata: Mapping[str, Any]) -> None:
    level, findings = classify(metadata)
    blocked = [item for item in findings if item.level >= DataLevel.L3_SENSITIVE]
    if blocked or level >= DataLevel.L4_PROHIBITED:
        raise DocumentMetadataError(
            "METADATA_SECURITY_VIOLATION",
            "Metadata contains prohibited or instruction-like content",
            details={"categories": sorted({item.category for item in blocked}), "finding_count": len(blocked)},
        )


def _conflict_value(field_name: str, value: Any) -> Any:
    _require_scalar(value, field_name=field_name)
    if field_name == "vendor":
        return canonical_vendor(value)
    if field_name == "document_category":
        return _canonical_enum(value, field_name=field_name, aliases=_CATEGORY_ALIASES, allowed=_DOCUMENT_CATEGORIES)[0]
    if field_name == "source_type":
        return _canonical_enum(value, field_name=field_name, aliases=_SOURCE_TYPE_ALIASES, allowed=_SOURCE_TYPES)[0]
    if field_name == "official_only":
        return _normalize_bool(value, field_name=field_name)
    return _normalize_text(value, field_name=field_name).lower()


def _quarantined_result(document: CleanedDocument, scan: DocumentSecurityScanResult) -> DocumentMetadataResult:
    document_hash = _document_hash(document)
    issues = tuple(
        MetadataIssue(code=code, field="security_scan", severity="quarantine", source="ing008", value_hash=_value_hash(code))
        for code in scan.reason_codes
    )
    payload = {"status": "quarantined", "reason_codes": list(scan.reason_codes), "document_hash": document_hash}
    metadata_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return DocumentMetadataResult(
        format=document.format,
        status=MetadataStatus.QUARANTINED,
        decision=MetadataDecision.QUARANTINE,
        entity_resolution_allowed=False,
        publication_allowed=False,
        metadata={},
        indexed_columns={},
        field_sources={},
        unknown_fields={},
        unresolved_values={},
        issues=issues,
        metadata_hash=metadata_hash,
        document_hash=document_hash,
        provenance={
            "parser_name": document.parser_name,
            "parser_version": document.parser_version,
            "cleaner_name": document.cleaning_name,
            "cleaner_version": document.cleaning_version,
            "security_scanner_name": scan.scanner_name,
            "security_scanner_version": scan.scanner_version,
        },
        warnings=("metadata_extraction_skipped_for_quarantined_document",),
    )


def extract_document_metadata(
    document: CleanedDocument,
    *,
    security_scan: DocumentSecurityScanResult,
    source_metadata: Mapping[str, Any] | None = None,
    filename: str = "",
    directory_path: str = "",
) -> DocumentMetadataResult:
    """Extract, normalize and validate Metadata after ING-007 and ING-008."""

    if not isinstance(document, CleanedDocument):
        raise DocumentMetadataError("METADATA_CLEANED_DOCUMENT_REQUIRED", "Metadata extraction requires an ING-007 cleaned document")
    if not isinstance(security_scan, DocumentSecurityScanResult):
        raise DocumentMetadataError("METADATA_SECURITY_SCAN_REQUIRED", "Metadata extraction requires an ING-008 security result")
    document_hash = _document_hash(document)
    if security_scan.document_hash != document_hash or security_scan.format != document.format:
        raise DocumentMetadataError("METADATA_SECURITY_SCAN_MISMATCH", "Security result does not match the cleaned document")
    if security_scan.decision != SecurityDecision.ALLOW or not security_scan.publication_allowed:
        return _quarantined_result(document, security_scan)

    parser_metadata = dict(document.metadata or {})
    operational = {key: copy.deepcopy(parser_metadata.pop(key)) for key in tuple(parser_metadata) if key in _OPERATIONAL_METADATA_FIELDS}
    source = _normalize_mapping(source_metadata, source="source_metadata")
    authored = _normalize_mapping(parser_metadata, source="document_metadata")
    source_owned = sorted(_SOURCE_OWNED_FIELDS & authored.keys())
    if source_owned:
        raise DocumentMetadataError(
            "METADATA_SOURCE_FIELD_FORBIDDEN",
            "Source-owned Metadata field is forbidden in document Metadata",
            details={"fields": source_owned},
        )
    _security_check({"source_metadata": source, "document_metadata": authored})

    for field_name in _SOURCE_CONFLICT_FIELDS & source.keys() & authored.keys():
        left = _conflict_value(field_name, source[field_name])
        right = _conflict_value(field_name, authored[field_name])
        if left != right:
            raise DocumentMetadataError("METADATA_SOURCE_CONFLICT", "Source and document Metadata conflict", details={"field": field_name})

    merged = dict(source)
    field_sources = {key: "source_metadata" for key in source}
    for key, value in authored.items():
        merged[key] = value
        field_sources[key] = "document_metadata"

    if not str(merged.get("title") or "").strip():
        title, title_source = _fallback_title(document, filename)
        merged["title"] = title
        field_sources["title"] = title_source

    result: dict[str, Any] = {}
    unknown_fields: dict[str, str] = {}
    unresolved_values: dict[str, str] = {}
    issues: list[MetadataIssue] = []

    for key, value in merged.items():
        if key not in _KNOWN_FIELDS:
            result[key] = copy.deepcopy(value)
            continue
        if key == "official_only" or key == "exclude_from_rag":
            normalized_bool = _normalize_bool(value, field_name=key)
            result[key] = normalized_bool
            if normalized_bool is None:
                unknown_fields[key] = "explicit_unknown"
                issues.append(MetadataIssue("METADATA_BOOLEAN_UNKNOWN", key, "review", field_sources.get(key, "unknown"), _value_hash(value)))
            continue
        if key in _LIST_FIELDS:
            result[key] = _normalize_list(value, field_name=key)
            continue
        if key == "vendor":
            _require_scalar(value, field_name=key)
            raw_vendor = _normalize_text(value, field_name=key, maximum=128)
            canonical = canonical_vendor(raw_vendor)
            if raw_vendor.lower() in _UNKNOWN_TOKENS or canonical not in _KNOWN_VENDORS:
                result[key] = UNKNOWN_VALUE
                unknown_fields[key] = "explicit_unknown" if raw_vendor.lower() in _UNKNOWN_TOKENS else "unrecognized_value"
                if raw_vendor and raw_vendor.lower() not in _UNKNOWN_TOKENS:
                    unresolved_values[key] = raw_vendor
                issues.append(MetadataIssue("METADATA_VENDOR_UNKNOWN", key, "review", field_sources.get(key, "unknown"), _value_hash(raw_vendor)))
            else:
                result[key] = canonical
            continue
        if key == "document_category":
            _require_scalar(value, field_name=key)
            canonical, reason = _canonical_enum(value, field_name=key, aliases=_CATEGORY_ALIASES, allowed=_DOCUMENT_CATEGORIES)
            result[key] = canonical
            if reason:
                unknown_fields[key] = reason
                unresolved_values[key] = _normalize_text(value, field_name=key, maximum=128)
                issues.append(MetadataIssue("METADATA_CATEGORY_UNKNOWN", key, "review", field_sources.get(key, "unknown"), _value_hash(value)))
            continue
        if key == "source_type":
            _require_scalar(value, field_name=key)
            canonical, reason = _canonical_enum(value, field_name=key, aliases=_SOURCE_TYPE_ALIASES, allowed=_SOURCE_TYPES)
            result[key] = canonical
            if reason:
                unknown_fields[key] = reason
                unresolved_values[key] = _normalize_text(value, field_name=key, maximum=128)
                issues.append(MetadataIssue("METADATA_SOURCE_TYPE_UNKNOWN", key, "review", field_sources.get(key, "unknown"), _value_hash(value)))
            continue
        if key == "status":
            _require_scalar(value, field_name=key)
            canonical, reason = _canonical_enum(value, field_name=key, aliases={}, allowed=_LIFECYCLE_STATUSES)
            result[key] = canonical
            if reason:
                unknown_fields[key] = reason
                unresolved_values[key] = _normalize_text(value, field_name=key, maximum=128)
                issues.append(MetadataIssue("METADATA_STATUS_UNKNOWN", key, "review", field_sources.get(key, "unknown"), _value_hash(value)))
            continue
        if key == "rag_priority":
            _require_scalar(value, field_name=key)
            if isinstance(value, bool):
                raise DocumentMetadataError("METADATA_PRIORITY_INVALID", "rag_priority must be an integer", details={"field": key})
            try:
                priority = int(value)
            except (TypeError, ValueError) as exc:
                raise DocumentMetadataError("METADATA_PRIORITY_INVALID", "rag_priority must be an integer", details={"field": key}) from exc
            if not 0 <= priority <= 100:
                raise DocumentMetadataError("METADATA_PRIORITY_INVALID", "rag_priority is outside the allowed range", details={"field": key})
            result[key] = priority
            continue
        _require_scalar(value, field_name=key)
        text = _normalize_text(value, field_name=key)
        result[key] = text.lower().replace("-", "_").replace(" ", "_") if key in _LOWER_FIELDS else text

    category_hint, vendor_hint = _directory_hints(directory_path)
    if category_hint:
        current = str(result.get("document_category") or "")
        if current not in {"", UNKNOWN_VALUE, category_hint}:
            raise DocumentMetadataError("METADATA_DIRECTORY_CONFLICT", "Directory category conflicts with document Metadata", details={"field": "document_category"})
        if current in {"", UNKNOWN_VALUE}:
            result["document_category"] = category_hint
            field_sources["document_category"] = "directory_hint"
            unknown_fields["document_category"] = "directory_hint_requires_review"
            issues.append(MetadataIssue("METADATA_DIRECTORY_HINT", "document_category", "review", "directory_hint", _value_hash(category_hint)))
    if vendor_hint:
        current = str(result.get("vendor") or "")
        if current not in {"", UNKNOWN_VALUE, vendor_hint}:
            raise DocumentMetadataError("METADATA_DIRECTORY_CONFLICT", "Directory vendor conflicts with document Metadata", details={"field": "vendor"})
        if current in {"", UNKNOWN_VALUE}:
            result["vendor"] = vendor_hint
            field_sources["vendor"] = "directory_hint"
            unknown_fields["vendor"] = "directory_hint_requires_review"
            issues.append(MetadataIssue("METADATA_DIRECTORY_HINT", "vendor", "review", "directory_hint", _value_hash(vendor_hint)))

    for field_name in REQUIRED_METADATA_FIELDS:
        if field_name == "status" and field_name not in result:
            result[field_name] = "draft"
            field_sources[field_name] = "safe_default"
            unknown_fields[field_name] = "missing_defaulted_draft"
            issues.append(MetadataIssue("METADATA_STATUS_DEFAULTED", field_name, "review", "safe_default"))
            continue
        value = result.get(field_name)
        missing = value is None or str(value).strip() == "" or str(value).upper() == UNKNOWN_VALUE
        if missing:
            result[field_name] = None if field_name == "official_only" else UNKNOWN_VALUE
            field_sources.setdefault(field_name, "default_unknown")
            unknown_fields.setdefault(field_name, "missing")
            issues.append(MetadataIssue("METADATA_REQUIRED_UNKNOWN", field_name, "review", field_sources[field_name]))

    for field_name in _APPLICABILITY_FIELDS:
        value = result.get(field_name)
        if value is None or str(value).strip().lower() in _UNKNOWN_TOKENS:
            result[field_name] = UNKNOWN_VALUE
            field_sources.setdefault(field_name, "default_unknown")
            unknown_fields.setdefault(field_name, "missing")

    category = str(result.get("document_category") or "")
    if category in _HIGH_RISK_CATEGORIES and all(result.get(field_name) == UNKNOWN_VALUE for field_name in ("os_family", "software_train", "cli_platform")):
        issues.append(MetadataIssue("METADATA_PLATFORM_SCOPE_UNKNOWN", "cli_platform", "review", "applicability"))
        unknown_fields.setdefault("cli_platform", "platform_scope_required")

    if result.get("official_only") is True and result.get("source_type") not in {
        "official",
        "official_url",
        "official_file",
        "product_page",
        "configuration_guide",
        "command_reference",
        "release_note",
        "product_support",
    }:
        raise DocumentMetadataError("METADATA_OFFICIAL_SOURCE_CONFLICT", "official_only conflicts with source_type", details={"field": "source_type"})

    result.setdefault("exclude_from_rag", False)
    result["metadata_contract_version"] = METADATA_CONTRACT_VERSION
    result["metadata_extractor_version"] = EXTRACTOR_VERSION
    canonical_payload = {
        "metadata": result,
        "field_sources": field_sources,
        "unknown_fields": unknown_fields,
        "unresolved_values": unresolved_values,
    }
    encoded = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise DocumentMetadataError("METADATA_TOO_LARGE", "Normalized Metadata exceeds the size limit")
    metadata_hash = hashlib.sha256(encoded).hexdigest()
    needs_review = bool(issues)
    status = MetadataStatus.UNKNOWN if needs_review else MetadataStatus.VALID
    decision = MetadataDecision.REVIEW if needs_review else MetadataDecision.PROCEED
    lifecycle = str(result.get("status") or "")
    publication_allowed = not needs_review and lifecycle in {"active", "published"} and result.get("exclude_from_rag") is False
    provenance = {
        "parser_name": document.parser_name,
        "parser_version": document.parser_version,
        "cleaner_name": document.cleaning_name,
        "cleaner_version": document.cleaning_version,
        "security_scanner_name": security_scan.scanner_name,
        "security_scanner_version": security_scan.scanner_version,
        "operational_metadata": operational,
    }
    return DocumentMetadataResult(
        format=document.format,
        status=status,
        decision=decision,
        entity_resolution_allowed=True,
        publication_allowed=publication_allowed,
        metadata=copy.deepcopy(result),
        indexed_columns=metadata_columns(result),
        field_sources=dict(field_sources),
        unknown_fields=dict(sorted(unknown_fields.items())),
        unresolved_values=dict(sorted(unresolved_values.items())),
        issues=tuple(issues),
        metadata_hash=metadata_hash,
        document_hash=document_hash,
        provenance=provenance,
        warnings=("unknown_metadata_requires_ing011_resolution",) if needs_review else (),
    )


__all__ = [
    "DocumentMetadataError",
    "DocumentMetadataResult",
    "EXTRACTOR_NAME",
    "EXTRACTOR_VERSION",
    "MAX_METADATA_BYTES",
    "METADATA_CONTRACT_VERSION",
    "MetadataDecision",
    "MetadataIssue",
    "MetadataStatus",
    "UNKNOWN_VALUE",
    "extract_document_metadata",
]
