"""ING-007 deterministic document-content cleaning boundary.

The parser in ING-006 deliberately returns structural HTML blocks, including
regions that are not knowledge content.  This module is the next stage: it
removes executable, hidden and boilerplate regions before metadata extraction
or chunking.  HTML cleaning is fail-closed when the original bytes are not
available, because a block-only representation has already lost the element
attributes needed to identify hidden and advertising content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Mapping

from services.document_parser_adapters import (
    MAX_PARSE_BYTES,
    ParsedBlock,
    ParsedDocument,
    parse_document,
)


CLEANER_NAME = "nexora-content-cleaner"
CLEANER_VERSION = "1.0.0"


class DocumentCleaningError(ValueError):
    """Stable, redacted cleaning error."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class CleanedDocument:
    format: str
    text: str
    blocks: tuple[ParsedBlock, ...]
    metadata: dict[str, Any]
    parser_name: str
    parser_version: str
    cleaning_name: str = CLEANER_NAME
    cleaning_version: str = CLEANER_VERSION
    clean_status: str = "cleaned"
    removed_regions: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "format": self.format,
            "blocks": [block.as_dict() for block in self.blocks],
            "metadata": dict(self.metadata),
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "cleaning_name": self.cleaning_name,
            "cleaning_version": self.cleaning_version,
            "clean_status": self.clean_status,
            "removed_regions": [dict(item) for item in self.removed_regions],
            "warnings": list(self.warnings),
        }
        if include_text:
            result["text"] = self.text
        return result


_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
    "ol",
}
_EXECUTABLE_TAGS = {"script", "style", "template", "noscript", "iframe", "object", "embed", "canvas"}
_NON_BODY_TAGS = {"head", "nav", "header", "footer", "aside", "form", "menu", "dialog"}
_FORM_CONTROL_TAGS = {"input", "button", "select", "textarea", "option"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_AD_MARKER_RE = re.compile(
    r"(?:^|[-_:./\s])(ad|ads|advert|advertisement|sponsor|sponsored|promo|promotion|banner|cookie|consent|newsletter|subscribe|social|share|related|breadcrumb|pagination|sidebar|popup|modal)(?:$|[-_:./\s])",
    re.IGNORECASE,
)
_HIDDEN_STYLE_RE = re.compile(
    r"(?:^|;)\s*(display|visibility|content-visibility|opacity)\s*:\s*([^;]+)",
    re.IGNORECASE,
)


def _attrs_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {str(name).lower(): str(value or "") for name, value in attrs}


def _hidden_reason(tag: str, attrs: Mapping[str, str]) -> str | None:
    if "hidden" in attrs:
        return "hidden_attribute"
    if attrs.get("type", "").strip().lower() == "hidden":
        return "hidden_attribute"
    if attrs.get("aria-hidden", "").strip().lower() in {"true", "1", "yes"}:
        return "aria_hidden"
    for property_name, value in _HIDDEN_STYLE_RE.findall(attrs.get("style", "")):
        normalized = value.strip().lower().replace("!important", "").strip()
        if property_name.lower() in {"display", "visibility", "content-visibility"} and normalized in {"none", "hidden", "collapse"}:
            return "hidden_style"
        if property_name.lower() == "opacity" and normalized in {"0", "0.0", "0.00"}:
            return "hidden_style"
    return None


def _region_reason(tag: str, attrs: Mapping[str, str], *, body_seen: bool) -> str | None:
    lowered = tag.lower()
    if lowered in _EXECUTABLE_TAGS:
        return f"{lowered}_region"
    if lowered in _NON_BODY_TAGS:
        return "non_body_region" if lowered not in {"nav", "header", "footer", "aside"} else lowered
    hidden = _hidden_reason(lowered, attrs)
    if hidden:
        return hidden
    if lowered in _FORM_CONTROL_TAGS:
        return "form_control"
    marker_values = " ".join(
        attrs.get(name, "")
        for name in ("id", "class", "role", "data-role", "data-component", "data-testid", "aria-label")
    ).strip()
    if marker_values and _AD_MARKER_RE.search(marker_values):
        return "boilerplate_or_advertisement"
    # A head outside the body is always non-content.  When a document has no
    # body tag, root-level text is retained for vendor HTML fragments.
    if lowered == "html":
        return None
    if not body_seen and lowered == "title":
        return "head_title"
    return None


class _HtmlContentCleaner(HTMLParser):
    """Attribute-aware HTML cleaner with bounded structural locators."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ParsedBlock] = []
        self.removed_regions: list[dict[str, Any]] = []
        self._buffer: list[str] = []
        self._block_type = "paragraph"
        self._block_start: tuple[int, int] | None = None
        self._stack: list[tuple[str, str | None]] = []
        self._skip_depth = 0
        self._body_seen = False
        self._in_body = False

    def _active(self) -> bool:
        return self._skip_depth == 0 and (self._in_body or not self._body_seen)

    def _flush(self) -> None:
        text = " ".join(part.strip() for part in self._buffer if part.strip()).strip()
        if text:
            line, column = self._block_start or self.getpos()
            self.blocks.append(ParsedBlock(text, self._block_type, {"line": line, "column": column}))
        self._buffer.clear()
        self._block_type = "paragraph"
        self._block_start = None

    def _push(self, tag: str, reason: str | None) -> None:
        self._stack.append((tag, reason))
        if reason:
            self._skip_depth += 1

    def _pop_void(self, tag: str) -> None:
        if self._stack and self._stack[-1][0] == tag:
            _, reason = self._stack.pop()
            if reason:
                self._skip_depth = max(0, self._skip_depth - 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        values = _attrs_map(attrs)
        if lowered == "body":
            self._body_seen = True
            self._in_body = True
        reason = _region_reason(lowered, values, body_seen=self._body_seen)
        if lowered == "body" and reason is None:
            self._push(lowered, None)
            return
        if self._skip_depth or (self._body_seen and not self._in_body):
            reason = None
        if reason:
            self._flush()
            line, column = self.getpos()
            self.removed_regions.append({"tag": lowered, "reason": reason, "line": line, "column": column})
            self._push(lowered, reason)
            if lowered in _VOID_TAGS:
                self._pop_void(lowered)
            return
        self._push(lowered, None)
        if not self._active():
            return
        if lowered in _BLOCK_TAGS:
            self._flush()
            if lowered.startswith("h"):
                self._block_type = "heading"
            elif lowered == "li":
                self._block_type = "list_item"
            elif lowered == "pre":
                self._block_type = "code"
            else:
                self._block_type = "paragraph"
        if lowered in _VOID_TAGS:
            self._pop_void(lowered)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        match_index = next((index for index in range(len(self._stack) - 1, -1, -1) if self._stack[index][0] == lowered), None)
        if match_index is None:
            return
        self._flush() if self._active() and lowered in _BLOCK_TAGS else None
        for _, reason in self._stack[match_index:]:
            if reason:
                self._skip_depth = max(0, self._skip_depth - 1)
        del self._stack[match_index:]
        if lowered == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if not self._active() or not data.strip():
            return
        if self._block_start is None:
            self._block_start = self.getpos()
        self._buffer.append(data)

    def handle_comment(self, data: str) -> None:
        # Comments can carry hidden instructions or tracking payloads; they
        # are never knowledge text.
        return

    def close(self) -> None:
        super().close()
        self._flush()


def _with_cleaning_metadata(document: ParsedDocument, *, removed_regions: tuple[dict[str, Any], ...], warnings: tuple[str, ...], status: str) -> dict[str, Any]:
    metadata = dict(document.metadata)
    metadata["content_cleaning"] = {
        "cleaner_name": CLEANER_NAME,
        "cleaner_version": CLEANER_VERSION,
        "status": status,
        "removed_region_count": len(removed_regions),
        "removed_region_reasons": sorted({str(item.get("reason", "")) for item in removed_regions}),
    }
    return metadata


def clean_document(document: ParsedDocument, *, raw_content: bytes | None = None) -> CleanedDocument:
    """Remove non-content regions from one parsed document.

    HTML requires the original bounded bytes.  Requiring them prevents an
    already-flattened block list from silently bypassing hidden/ad regions.
    Other formats retain parser blocks and receive the same explicit cleaning
    metadata contract.
    """

    if not isinstance(document, ParsedDocument):
        raise DocumentCleaningError("CLEAN_PARSED_DOCUMENT_REQUIRED", "Cleaning input must be a ParsedDocument")
    if document.format != "html":
        blocks = tuple(block for block in document.blocks if block.text.strip())
        text = "\n\n".join(block.text.strip() for block in blocks)
        status = "cleaned" if text else "empty_after_cleaning"
        warnings = ("document_empty_after_cleaning",) if not text and document.text else ()
        return CleanedDocument(
            document.format,
            text,
            blocks,
            _with_cleaning_metadata(document, removed_regions=(), warnings=warnings, status=status),
            document.parser_name,
            document.parser_version,
            clean_status=status,
            warnings=warnings,
        )

    if raw_content is None:
        raise DocumentCleaningError("CLEAN_HTML_RAW_REQUIRED", "HTML cleaning requires original document bytes")
    if not isinstance(raw_content, bytes):
        raise DocumentCleaningError("CLEAN_BYTES_REQUIRED", "Cleaning input must be bytes")
    if len(raw_content) > MAX_PARSE_BYTES:
        raise DocumentCleaningError("CLEAN_DOCUMENT_TOO_LARGE", "Document exceeds cleaning size limit")
    try:
        source = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentCleaningError("CLEAN_ENCODING_INVALID", "HTML document is not valid UTF-8") from exc
    cleaner = _HtmlContentCleaner()
    try:
        cleaner.feed(source)
        cleaner.close()
    except Exception as exc:
        raise DocumentCleaningError("CLEAN_HTML_INVALID", "HTML content could not be cleaned") from exc
    blocks = tuple(cleaner.blocks)
    text = "\n\n".join(block.text for block in blocks)
    removed = tuple(dict(item) for item in cleaner.removed_regions)
    warnings = ("html_body_empty_after_cleaning",) if not text else ()
    status = "empty_after_cleaning" if not text else "cleaned"
    return CleanedDocument(
        document.format,
        text,
        blocks,
        _with_cleaning_metadata(document, removed_regions=removed, warnings=warnings, status=status),
        document.parser_name,
        document.parser_version,
        clean_status=status,
        removed_regions=removed,
        warnings=warnings,
    )


def parse_and_clean_document(content: bytes, *, filename: str = "", content_type: str = "") -> CleanedDocument:
    """Run the canonical ING-006 parser followed by ING-007 cleaning."""

    if not isinstance(content, bytes):
        raise DocumentCleaningError("CLEAN_BYTES_REQUIRED", "Cleaning input must be bytes")
    document = parse_document(content, filename=filename, content_type=content_type)
    return clean_document(document, raw_content=content if document.format == "html" else None)


__all__ = [
    "CLEANER_NAME",
    "CLEANER_VERSION",
    "CleanedDocument",
    "DocumentCleaningError",
    "clean_document",
    "parse_and_clean_document",
]
