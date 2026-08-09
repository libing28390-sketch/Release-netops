"""ING-006 unified HTML/Markdown/TXT/PDF parser adapter boundary.

Adapters only decode and structurally extract source bytes.  They do not make
trust, publication, prompt-injection, or content-cleaning decisions; those are
owned by later ING-007/ING-008 stages.  Every adapter returns the same bounded
`ParsedDocument` contract and never performs network I/O.
"""

from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Mapping, Protocol

from ai.services.knowledge_metadata import parse_markdown_document


MAX_PARSE_BYTES = 20_000_000
SUPPORTED_FORMATS = ("html", "markdown", "txt", "pdf")
_EXTENSION_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".text": "txt",
    ".pdf": "pdf",
}
_MIME_FORMATS = {
    "text/html": "html",
    "text/markdown": "markdown",
    "text/plain": "txt",
    "application/pdf": "pdf",
}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DocumentParserError(ValueError):
    """Stable, safe parser error without source body or dependency details."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    block_type: str = "paragraph"
    locator: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "block_type": self.block_type, "locator": dict(self.locator)}


@dataclass(frozen=True)
class ParsedDocument:
    format: str
    text: str
    blocks: tuple[ParsedBlock, ...]
    metadata: dict[str, Any]
    parser_name: str
    parser_version: str
    parse_status: str = "parsed"
    warnings: tuple[str, ...] = ()

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "format": self.format,
            "blocks": [block.as_dict() for block in self.blocks],
            "metadata": dict(self.metadata),
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "parse_status": self.parse_status,
            "warnings": list(self.warnings),
        }
        if include_text:
            result["text"] = self.text
        return result


class DocumentParserAdapter(Protocol):
    format_name: str
    parser_name: str
    parser_version: str

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        ...


def _decode_utf8(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParserError("PARSER_ENCODING_INVALID", "Document text is not valid UTF-8") from exc
    if _CONTROL_RE.search(text):
        raise DocumentParserError("PARSER_CONTROL_BYTES", "Document text contains forbidden control bytes")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _blocks_from_lines(text: str, *, block_type: str = "paragraph") -> tuple[ParsedBlock, ...]:
    blocks: list[ParsedBlock] = []
    for index, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if value:
            blocks.append(ParsedBlock(value, block_type, {"line_start": index, "line_end": index}))
    if not blocks and text:
        blocks.append(ParsedBlock(text.strip(), block_type, {"line_start": 1, "line_end": 1}))
    return tuple(blocks)


class TxtParserAdapter:
    format_name = "txt"
    parser_name = "nexora-txt"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        return ParsedDocument(self.format_name, text, _blocks_from_lines(text), {}, self.parser_name, self.parser_version)


class MarkdownParserAdapter:
    format_name = "markdown"
    parser_name = "nexora-markdown"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        raw = _decode_utf8(content)
        try:
            parsed = parse_markdown_document(raw)
        except Exception as exc:
            if hasattr(exc, "code"):
                raise
            raise DocumentParserError("PARSER_MARKDOWN_FRONT_MATTER_INVALID", "Markdown Front Matter is invalid") from exc
        text = parsed.content
        warnings = ("front_matter_missing",) if parsed.metadata_parse_status == "missing" else ()
        return ParsedDocument(
            self.format_name,
            text,
            _blocks_from_lines(text, block_type="markdown_line"),
            dict(parsed.metadata),
            self.parser_name,
            self.parser_version,
            parse_status="parsed" if parsed.metadata_parse_status in {"missing", "parsed"} else parsed.metadata_parse_status,
            warnings=warnings,
        )


class _HTMLTextParser(HTMLParser):
    _BLOCK_TAGS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ParsedBlock] = []
        self._buffer: list[str] = []
        self._block_type = "paragraph"
        self._skip_depth = 0

    def _flush(self) -> None:
        text = " ".join(part.strip() for part in self._buffer if part.strip()).strip()
        if text:
            line, column = self.getpos()
            self.blocks.append(ParsedBlock(text, self._block_type, {"line": line, "column": column}))
        self._buffer.clear()
        self._block_type = "paragraph"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered in self._BLOCK_TAGS:
            self._flush()
            self._block_type = "heading" if lowered.startswith("h") else ("list_item" if lowered == "li" else "paragraph")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if lowered in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


class HtmlParserAdapter:
    format_name = "html"
    parser_name = "nexora-html"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        parser = _HTMLTextParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            raise DocumentParserError("PARSER_HTML_INVALID", "HTML structure could not be parsed") from exc
        blocks = tuple(parser.blocks)
        body = "\n\n".join(block.text for block in blocks)
        return ParsedDocument(
            self.format_name,
            body,
            blocks,
            {},
            self.parser_name,
            self.parser_version,
            warnings=("html_requires_ing007_content_cleaning",),
        )


def _pdf_string(value: bytes) -> str:
    output = bytearray()
    index = 0
    while index < len(value):
        byte = value[index]
        if byte != 0x5C:  # backslash
            output.append(byte)
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        escaped = value[index]
        simple = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
        if escaped in simple:
            output.append(simple[escaped])
            index += 1
        elif 48 <= escaped <= 55:
            digits = [escaped]
            index += 1
            while index < len(value) and len(digits) < 3 and 48 <= value[index] <= 55:
                digits.append(value[index])
                index += 1
            output.append(int(bytes(digits), 8))
        else:
            output.append(escaped)
            index += 1
    return output.decode("utf-8", errors="replace")


def _pdf_fallback_text(content: bytes) -> str:
    streams = [content]
    for match in re.finditer(rb"<<(?P<dict>.*?)>>\s*stream\r?\n(?P<body>.*?)\r?\nendstream", content, flags=re.DOTALL):
        body = match.group("body")
        if b"/FlateDecode" in match.group("dict"):
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        streams.append(body)
    extracted: list[str] = []
    string_pattern = re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj")
    array_pattern = re.compile(rb"\[(.*?)\]\s*TJ", flags=re.DOTALL)
    for stream in streams:
        for match in string_pattern.finditer(stream):
            raw = match.group(0)
            start, end = raw.find(b"("), raw.rfind(b")")
            if start >= 0 and end > start:
                extracted.append(_pdf_string(raw[start + 1 : end]))
        for match in array_pattern.finditer(stream):
            extracted.extend(_pdf_string(item) for item in re.findall(rb"\((?:\\.|[^()\\])*\)", match.group(1)) for item in (item[1:-1],))
    return " ".join(item.strip() for item in extracted if item.strip()).strip()


def _optional_pdf_extract(content: bytes) -> tuple[str, int] | None:
    if b"startxref" not in content:
        return None
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        text = "\n".join(str(page.extract_text() or "") for page in reader.pages).strip()
        return text, len(reader.pages)
    except Exception:
        # A valid magic header is enough to enter the adapter boundary.  Some
        # vendor PDFs use constructs an optional backend cannot read; the
        # deterministic operator fallback below still extracts simple text
        # operators and reports a degraded result instead of leaking backend
        # exception details.
        return None


class PdfParserAdapter:
    format_name = "pdf"
    parser_name = "nexora-pdf"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        if not content.startswith(b"%PDF-"):
            raise DocumentParserError("PARSER_PDF_MAGIC_INVALID", "PDF magic bytes are missing")
        optional = _optional_pdf_extract(content)
        page_count = 0
        if optional is not None:
            text, page_count = optional
        else:
            text = _pdf_fallback_text(content)
            page_count = max(0, len(re.findall(rb"/Type\s*/Page\b", content)))
        blocks = _blocks_from_lines(text, block_type="pdf_text")
        warnings = () if text else ("pdf_text_extraction_degraded",)
        return ParsedDocument(
            self.format_name,
            text,
            blocks,
            {"page_count": page_count},
            self.parser_name,
            self.parser_version,
            parse_status="parsed" if text else "degraded",
            warnings=warnings,
        )


def _format_from_inputs(content: bytes, filename: str, content_type: str) -> str:
    normalized_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    mime_format = _MIME_FORMATS.get(normalized_mime, "")
    lowered = str(filename or "").lower()
    extension = next((suffix for suffix in _EXTENSION_FORMATS if lowered.endswith(suffix)), "")
    extension_format = _EXTENSION_FORMATS.get(extension, "")
    if mime_format and extension_format and mime_format != extension_format:
        raise DocumentParserError("PARSER_FORMAT_MISMATCH", "Filename extension and content type disagree")
    if content.startswith(b"%PDF-"):
        detected = "pdf"
        if (mime_format and mime_format != "pdf") or (extension_format and extension_format != "pdf"):
            raise DocumentParserError("PARSER_FORMAT_MISMATCH", "PDF magic does not match the declared file format")
    else:
        detected = mime_format or extension_format
    if detected not in SUPPORTED_FORMATS:
        raise DocumentParserError("PARSER_FORMAT_UNSUPPORTED", "Document format is not supported")
    if detected == "pdf" and not content.startswith(b"%PDF-"):
        raise DocumentParserError("PARSER_PDF_MAGIC_INVALID", "PDF magic bytes are missing")
    return detected


class DocumentParserRegistry:
    def __init__(self, adapters: Mapping[str, DocumentParserAdapter] | None = None) -> None:
        self._adapters: dict[str, DocumentParserAdapter] = dict(adapters or {
            "html": HtmlParserAdapter(),
            "markdown": MarkdownParserAdapter(),
            "txt": TxtParserAdapter(),
            "pdf": PdfParserAdapter(),
        })
        if set(self._adapters) != set(SUPPORTED_FORMATS):
            raise DocumentParserError("PARSER_REGISTRY_INVALID", "Parser registry must provide exactly four formats")

    def formats(self) -> tuple[str, ...]:
        return tuple(SUPPORTED_FORMATS)

    def get(self, format_name: str) -> DocumentParserAdapter:
        try:
            return self._adapters[str(format_name).lower()]
        except KeyError as exc:
            raise DocumentParserError("PARSER_FORMAT_UNSUPPORTED", "Document format is not supported") from exc

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        if not isinstance(content, bytes):
            raise DocumentParserError("PARSER_BYTES_REQUIRED", "Parser input must be bytes")
        if not content:
            raise DocumentParserError("PARSER_EMPTY_DOCUMENT", "Document content cannot be empty")
        if len(content) > MAX_PARSE_BYTES:
            raise DocumentParserError("PARSER_DOCUMENT_TOO_LARGE", "Document exceeds parser size limit")
        format_name = _format_from_inputs(content, filename, content_type)
        return self.get(format_name).parse(content, filename=filename, content_type=content_type)


document_parser_registry = DocumentParserRegistry()


def parse_document(content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
    """Parse through the canonical four-format registry."""
    return document_parser_registry.parse(content, filename=filename, content_type=content_type)


__all__ = [
    "DocumentParserAdapter",
    "DocumentParserError",
    "DocumentParserRegistry",
    "HtmlParserAdapter",
    "MarkdownParserAdapter",
    "ParsedBlock",
    "ParsedDocument",
    "PdfParserAdapter",
    "TxtParserAdapter",
    "document_parser_registry",
    "parse_document",
]
