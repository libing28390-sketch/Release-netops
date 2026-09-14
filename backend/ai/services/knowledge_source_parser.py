"""Canonical parser boundary for direct Knowledge document imports.

The UI accepts a small, explicit set of file extensions.  This module makes
the server apply the same rules as the official ingestion pipeline before a
document is previewed, confirmed, chunked, or reindexed.  Markdown keeps its
YAML Front Matter; structured files are validated and converted to searchable
plain text; CLI/config files remain lossless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ai.services.knowledge_metadata import MetadataParseError, parse_markdown_document
from ai.services.knowledge_document_contract import DOCUMENT_CONTRACT_NAME
from services.document_parser_adapters import DocumentParserError, ParsedDocument, parse_document


_SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".log",
    ".html",
    ".htm",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".xml",
    ".conf",
    ".cfg",
    ".ini",
}


class KnowledgeSourceParseError(ValueError):
    """Stable parser error safe to expose at the metadata preview boundary."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class ParsedKnowledgeSource:
    original_content: str
    content: str
    metadata: dict[str, Any]
    metadata_parse_status: str
    metadata_parse_error: str | None
    format: str
    parser_name: str
    parser_version: str
    warnings: tuple[str, ...] = ()


def _extension(filename: str) -> str:
    lowered = str(filename or "").strip().lower()
    dot = lowered.rfind(".")
    return lowered[dot:] if dot > 0 else ""


def _structured_document_envelope(
    raw_text: str,
    *,
    extension: str,
    parsed: ParsedDocument,
) -> ParsedKnowledgeSource | None:
    """Extract the explicit JSON/YAML document envelope when present.

    Arbitrary JSON/YAML remains a searchable structured document.  Only a
    mapping with the Nexora format marker (or both ``metadata`` and
    ``content`` keys) is treated as an import envelope.  This prevents a
    user's inventory JSON from silently changing its meaning while giving
    custom exporters a deterministic metadata/body contract.
    """

    if extension not in {".json", ".yaml", ".yml"}:
        return None
    try:
        if extension == ".json":
            import json

            value = json.loads(raw_text)
        else:
            import yaml  # type: ignore

            value = yaml.safe_load(raw_text)
    except Exception as exc:  # canonical adapter already reports syntax errors
        raise KnowledgeSourceParseError("PARSER_DOCUMENT_ENVELOPE_INVALID", "Custom document envelope is invalid") from exc
    if not isinstance(value, Mapping):
        return None

    marker = str(value.get("format") or "").strip().lower()
    has_envelope_keys = "metadata" in value or "content" in value
    schema_version = str(value.get("schema_version") or "").strip()
    is_envelope = marker == DOCUMENT_CONTRACT_NAME or (has_envelope_keys and bool(schema_version))
    if not is_envelope:
        return None

    metadata = value.get("metadata")
    content = value.get("content")
    if not isinstance(metadata, Mapping) or not isinstance(content, str):
        raise KnowledgeSourceParseError(
            "PARSER_DOCUMENT_ENVELOPE_INVALID",
            "Custom document envelope requires a metadata mapping and string content",
        )
    if not content.strip():
        raise KnowledgeSourceParseError("PARSER_EMPTY_DOCUMENT", "Document content cannot be empty")

    normalized_metadata = {str(key): item for key, item in metadata.items()}
    normalized_metadata.setdefault("schema_version", schema_version or "2.0")
    return ParsedKnowledgeSource(
        original_content=raw_text,
        content=content.replace("\r\n", "\n").replace("\r", "\n"),
        metadata=normalized_metadata,
        metadata_parse_status="parsed",
        metadata_parse_error=None,
        format=parsed.format,
        parser_name=f"{parsed.parser_name}-document-envelope",
        parser_version=parsed.parser_version,
        warnings=tuple(parsed.warnings) + ("structured_document_envelope",),
    )


def parse_knowledge_source(content: str, *, filename: str = "") -> ParsedKnowledgeSource:
    """Parse one direct-import body using its declared filename extension."""

    original = str(content or "")
    if not original.strip():
        raise KnowledgeSourceParseError("PARSER_EMPTY_DOCUMENT", "Document content cannot be empty")
    extension = _extension(filename)
    if extension not in _SUPPORTED_EXTENSIONS:
        # Backward-compatible manual-paste path: no extension means Markdown
        # semantics, including optional Front Matter.
        try:
            parsed = parse_markdown_document(original)
        except MetadataParseError as exc:
            raise KnowledgeSourceParseError("PARSER_MARKDOWN_FRONT_MATTER_INVALID", "Metadata Front Matter is invalid") from exc
        return ParsedKnowledgeSource(
            original_content=parsed.original_content,
            content=parsed.content,
            metadata=dict(parsed.metadata),
            metadata_parse_status=parsed.metadata_parse_status,
            metadata_parse_error=parsed.metadata_parse_error,
            format="markdown",
            parser_name="nexora-markdown-legacy-text",
            parser_version="1.0.0",
            warnings=("filename_extension_missing_markdown_fallback",),
        )

    try:
        parsed: ParsedDocument = parse_document(original.encode("utf-8"), filename=filename)
    except DocumentParserError as exc:
        raise KnowledgeSourceParseError(exc.code, exc.message, details=exc.details) from exc

    envelope = _structured_document_envelope(original, extension=extension, parsed=parsed)
    if envelope is not None:
        return envelope

    # HTML needs the attribute-aware cleaner before it becomes tenant RAG
    # content; the parser alone intentionally retains structural regions for
    # the later ING-007 stage.
    if parsed.format == "html":
        try:
            from services.document_content_cleaning import parse_and_clean_document

            cleaned = parse_and_clean_document(original.encode("utf-8"), filename=filename)
            parsed_text = cleaned.text
            parsed_metadata = dict(cleaned.metadata)
            parsed_warnings = tuple(parsed.warnings) + tuple(cleaned.warnings)
        except Exception as exc:
            raise KnowledgeSourceParseError("PARSER_HTML_INVALID", "HTML document could not be cleaned") from exc
    else:
        parsed_text = parsed.text
        parsed_metadata = dict(parsed.metadata)
        parsed_warnings = tuple(parsed.warnings)

    # Only Markdown has semantic YAML Front Matter in the current contract.
    # Other formats may carry structured content but their import metadata is
    # supplied by the UI/metadata fields and never guessed from arbitrary keys.
    metadata_status = "missing"
    warnings = parsed_warnings
    if parsed.format == "markdown":
        metadata_status = "missing" if "front_matter_missing" in parsed.warnings else "parsed"
    return ParsedKnowledgeSource(
        original_content=original,
        content=parsed_text,
        metadata=parsed_metadata,
        metadata_parse_status=metadata_status,
        metadata_parse_error=None,
        format=parsed.format,
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        warnings=warnings,
    )


__all__ = ["KnowledgeSourceParseError", "ParsedKnowledgeSource", "parse_knowledge_source"]
