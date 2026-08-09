"""Front Matter parsing, validation, and canonical metadata helpers.

Knowledge documents use a YAML Front Matter block as their semantic source of
truth.  The import directory is deliberately treated as a validation hint;
it can never overwrite values authored in the document itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

try:  # PyYAML is a small, explicit runtime dependency of the ingestion path.
    import yaml
except ImportError:  # pragma: no cover - surfaced as a useful configuration error
    yaml = None  # type: ignore[assignment]


ROOT_CATEGORY_MAP = {
    "01_product": "hardware",
    "02_commands": "command",
    "03_configuration": "configuration",
    "04_cli_outputs": "cli_output",
    "05_troubleshooting": "troubleshooting",
    "06_examples": "example",
}
DIRECTORY_VENDOR_MAP = {
    "huawei": "Huawei",
    "h3c": "H3C",
    "cisco": "Cisco",
    "ruijie": "Ruijie",
}
REQUIRED_METADATA_FIELDS = (
    "schema_version",
    "document_id",
    "title",
    "vendor",
    "product_type",
    "document_category",
    "source_type",
    "official_only",
    "status",
)
HIGH_FREQUENCY_METADATA_FIELDS = (
    "document_id",
    "vendor",
    "document_category",
    "product_family",
    "product_series",
    "product_model",
    "os_family",
    "os_generation",
    "software_train",
    "software_release",
    "cli_platform",
    "feature_domain",
    "feature",
    "subfeature",
    "risk_level",
    "verification_level",
    "rag_priority",
    "status",
)


class MetadataParseError(ValueError):
    """Raised when a document starts as Front Matter but contains invalid YAML."""


class MetadataValidationError(ValueError):
    """Raised when required metadata or directory consistency checks fail."""


@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    original_content: str
    content: str
    metadata: dict[str, Any]
    metadata_parse_status: str
    metadata_parse_error: Optional[str] = None


_OPENING_RE = re.compile(r"\A(?:\ufeff)?---[ \t]*(?:\r?\n|\Z)")


def _normalise_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MetadataParseError("YAML Front Matter must be a mapping")
    result: dict[str, Any] = {}
    for key, item in value.items():
        canonical_key = str(key).strip().lower().replace("-", "_")
        result[canonical_key] = item
    return result


def parse_markdown_document(raw_text: str) -> ParsedKnowledgeDocument:
    """Parse only a Front Matter block at byte zero.

    A later ``---`` in the Markdown body is ordinary content.  If the file
    begins with an opening marker but has no closing marker, it is rejected
    rather than silently indexed with a partial header.
    """

    original = str(raw_text or "")
    text = original.replace("\r\n", "\n").replace("\r", "\n")
    opening = _OPENING_RE.match(text)
    if not opening:
        return ParsedKnowledgeDocument(original, text, {}, "missing")

    rest = text[opening.end():]
    closing = re.search(r"^---[ \t]*$", rest, flags=re.MULTILINE)
    if not closing:
        raise MetadataParseError("Front Matter opening marker has no closing --- marker")

    yaml_text = rest[:closing.start()]
    body = rest[closing.end():]
    if body.startswith("\n"):
        body = body[1:]
    if yaml is None:
        raise MetadataParseError("PyYAML is required to parse knowledge metadata")
    try:
        loaded = yaml.safe_load(yaml_text) or {}
    except Exception as exc:  # yaml.YAMLError differs across supported versions
        raise MetadataParseError(f"Invalid YAML Front Matter: {exc}") from exc
    metadata = _normalise_mapping(loaded)
    return ParsedKnowledgeDocument(original, body, metadata, "parsed")


def _first_path_parts(directory_path: str | None) -> tuple[str | None, str | None]:
    parts = [part.strip().lower() for part in str(directory_path or "").replace("\\", "/").split("/") if part.strip()]
    if parts and parts[0] == "kb_import":
        parts = parts[1:]
    if not parts:
        return None, None
    root = parts[0]
    vendor = parts[1] if len(parts) > 1 else None
    return root, vendor


def is_system_registry_document(name: str | None, metadata: Mapping[str, Any] | None = None) -> bool:
    """Recognise the metadata schema/registry itself as non-RAG content."""

    lowered = str(name or "").lower()
    data = metadata or {}
    document_type = str(data.get("document_type") or "").lower()
    return (
        "metadata_schema" in document_type
        or "rag_metadata_schema" in lowered
        or "nexora_network_kb_metadata_schema" in lowered
        or str(data.get("exclude_from_rag") or "").lower() in {"1", "true", "yes"}
    )


def validate_metadata(
    metadata: Mapping[str, Any],
    *,
    directory_path: str | None = None,
    name: str | None = None,
    allow_missing_required: bool = False,
) -> dict[str, Any]:
    """Validate and canonicalise metadata without allowing directory overrides."""

    result = _normalise_mapping(dict(metadata))
    missing = [field for field in REQUIRED_METADATA_FIELDS if field not in result]
    if missing and not allow_missing_required:
        raise MetadataValidationError("Missing required metadata: " + ", ".join(missing))

    if "official_only" in result and not isinstance(result["official_only"], bool):
        # YAML values such as ``"true"`` are common in hand-written files.
        value = str(result["official_only"]).strip().lower()
        if value in {"true", "yes", "1"}:
            result["official_only"] = True
        elif value in {"false", "no", "0"}:
            result["official_only"] = False
        else:
            raise MetadataValidationError("official_only must be a boolean")

    category = str(result.get("document_category") or "").strip().lower()
    if category:
        result["document_category"] = category
    vendor = str(result.get("vendor") or "").strip()
    if vendor:
        result["vendor"] = canonical_vendor(vendor)

    root, directory_vendor = _first_path_parts(directory_path)
    expected_category = ROOT_CATEGORY_MAP.get(root or "")
    if expected_category and category and category != expected_category:
        raise MetadataValidationError(
            f"Directory category '{expected_category}' conflicts with metadata document_category '{category}'"
        )
    if expected_category and not category:
        result["document_category"] = expected_category
    expected_vendor = DIRECTORY_VENDOR_MAP.get(directory_vendor or "")
    if expected_vendor and vendor and canonical_vendor(vendor) != expected_vendor:
        raise MetadataValidationError(
            f"Directory vendor '{expected_vendor}' conflicts with metadata vendor '{vendor}'"
        )
    # A directory hint is retained for audit, never used to replace metadata.
    if root:
        result.setdefault("knowledge_directory_root", root)
    if directory_vendor:
        result.setdefault("knowledge_directory_vendor", directory_vendor)

    if is_system_registry_document(name, result):
        result["exclude_from_rag"] = True
    else:
        result.setdefault("exclude_from_rag", False)

    # ``cli_platform`` is intentionally nullable.  In particular, V300/V600
    # software trains do not, on their own, identify a CLI platform.
    if not str(result.get("cli_platform") or "").strip():
        result["cli_platform"] = None
    return result


def canonical_vendor(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "huawei": "Huawei",
        "华为": "Huawei",
        "h3c": "H3C",
        "cisco": "Cisco",
        "思科": "Cisco",
        "ruijie": "Ruijie",
        "锐捷": "Ruijie",
        "all": "all",
    }.get(normalized, str(value or "").strip())


def merge_metadata(frontmatter: Mapping[str, Any], source_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge source/audit metadata while giving Front Matter precedence."""

    merged: dict[str, Any] = {}
    for key, value in (source_metadata or {}).items():
        if value is not None:
            merged[str(key)] = value
    for key, value in frontmatter.items():
        merged[str(key)] = value
    return merged


def json_safe_metadata(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), default=str)


def metadata_columns(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the indexed scalar columns; arrays remain in metadata_json."""

    result: dict[str, Any] = {}
    for field in HIGH_FREQUENCY_METADATA_FIELDS:
        value = metadata.get(field)
        if isinstance(value, (list, dict, tuple, set)):
            continue
        result[field] = value
    # Keep a stable alias for singular model filtering while accepting the
    # schema's historical ``product_models`` array.
    if not result.get("product_model"):
        models = metadata.get("product_models") or metadata.get("applicable_product_models")
        if isinstance(models, (list, tuple)) and len(models) == 1:
            result["product_model"] = models[0]
    return result
