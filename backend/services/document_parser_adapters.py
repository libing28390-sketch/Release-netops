"""ING-006 unified text/structured/HTML/PDF/DOCX parser adapter boundary.

Adapters only decode and structurally extract source bytes.  They do not make
trust, publication, prompt-injection, or content-cleaning decisions; those are
owned by later ING-007/ING-008 stages.  Every adapter returns the same bounded
`ParsedDocument` contract and never performs network I/O.
"""

from __future__ import annotations

import io
import csv
import json
import re
import zlib
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Mapping, Protocol

from ai.services.knowledge_metadata import parse_markdown_document


MAX_PARSE_BYTES = 20_000_000
SUPPORTED_FORMATS = ("html", "markdown", "txt", "json", "yaml", "csv", "xml", "config", "pdf", "docx")
_EXTENSION_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".text": "txt",
    ".log": "txt",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".xml": "xml",
    ".conf": "config",
    ".cfg": "config",
    ".ini": "config",
    ".pdf": "pdf",
    ".docx": "docx",
}
_MIME_FORMATS = {
    "text/html": "html",
    "text/markdown": "markdown",
    "text/plain": "txt",
    "application/json": "json",
    "text/csv": "csv",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/yaml": "yaml",
    "text/yaml": "yaml",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
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


class JsonParserAdapter:
    """Validate JSON and render it deterministically for retrieval."""

    format_name = "json"
    parser_name = "nexora-json"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DocumentParserError("PARSER_JSON_INVALID", "JSON document is invalid") from exc
        normalized = json.dumps(value, ensure_ascii=False, indent=2)
        return ParsedDocument(
            self.format_name,
            normalized,
            _blocks_from_lines(normalized, block_type="json_line"),
            {"structured_format": "json"},
            self.parser_name,
            self.parser_version,
        )


class YamlParserAdapter:
    """Validate YAML while preserving comments and operator-authored layout."""

    format_name = "yaml"
    parser_name = "nexora-yaml"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        try:
            import yaml  # type: ignore
            yaml.safe_load(text)
        except ImportError as exc:
            raise DocumentParserError("PARSER_YAML_UNAVAILABLE", "YAML parser is not available") from exc
        except Exception as exc:
            raise DocumentParserError("PARSER_YAML_INVALID", "YAML document is invalid") from exc
        return ParsedDocument(
            self.format_name,
            text,
            _blocks_from_lines(text, block_type="yaml_line"),
            {"structured_format": "yaml"},
            self.parser_name,
            self.parser_version,
        )


class CsvParserAdapter:
    """Parse CSV rows into searchable, delimiter-independent text blocks."""

    format_name = "csv"
    parser_name = "nexora-csv"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        try:
            sample = text[:8192]
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample else csv.excel
        except csv.Error:
            dialect = csv.excel
        try:
            rows = list(csv.reader(io.StringIO(text), dialect=dialect, strict=True))
        except csv.Error as exc:
            raise DocumentParserError("PARSER_CSV_INVALID", "CSV document is invalid") from exc
        if not rows:
            raise DocumentParserError("PARSER_EMPTY_DOCUMENT", "Document content cannot be empty")
        normalized = "\n".join(" | ".join(str(cell).strip() for cell in row).strip() for row in rows)
        return ParsedDocument(
            self.format_name,
            normalized,
            _blocks_from_lines(normalized, block_type="csv_row"),
            {"structured_format": "csv", "row_count": len(rows)},
            self.parser_name,
            self.parser_version,
        )


class XmlParserAdapter:
    """Validate XML and expose leaf text without indexing markup noise."""

    format_name = "xml"
    parser_name = "nexora-xml"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise DocumentParserError("PARSER_XML_INVALID", "XML document is invalid") from exc
        lines: list[str] = []
        for element in root.iter():
            children = list(element)
            value = " ".join(part.strip() for part in element.itertext() if part and part.strip()).strip()
            if value and not children:
                lines.append(value)
        normalized = "\n".join(lines) or text.strip()
        return ParsedDocument(
            self.format_name,
            normalized,
            _blocks_from_lines(normalized, block_type="xml_text"),
            {"structured_format": "xml", "root_tag": str(root.tag)},
            self.parser_name,
            self.parser_version,
            parse_status="parsed" if lines else "degraded",
            warnings=() if lines else ("xml_text_extraction_degraded",),
        )


class ConfigParserAdapter:
    """Keep CLI/config syntax lossless; syntax is intentionally not guessed."""

    format_name = "config"
    parser_name = "nexora-config"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        text = _decode_utf8(content)
        return ParsedDocument(
            self.format_name,
            text,
            _blocks_from_lines(text, block_type="config_line"),
            {"structured_format": "config"},
            self.parser_name,
            self.parser_version,
        )


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


class DocxParserAdapter:
    """Extract readable paragraphs and table rows from an OOXML document.

    The boundary intentionally ignores images, macros, embedded objects and
    external relationships. It provides deterministic text for the normal
    content-cleaning/chunking stages without a third-party DOCX dependency.
    """

    format_name = "docx"
    parser_name = "nexora-docx"
    parser_version = "1.0.0"
    _NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    @classmethod
    def _paragraph_text(cls, paragraph: ET.Element) -> str:
        parts: list[str] = []
        for node in paragraph.iter():
            local = str(node.tag).rsplit("}", 1)[-1]
            if local == "t":
                parts.append(node.text or "")
            elif local == "tab":
                parts.append("\t")
            elif local in {"br", "cr"}:
                parts.append("\n")
        return "".join(parts).strip()

    @classmethod
    def _heading_level(cls, paragraph: ET.Element) -> int:
        style = paragraph.find("./w:pPr/w:pStyle", cls._NS)
        value = str(style.attrib.get(f"{{{cls._NS['w']}}}val") or "") if style is not None else ""
        match = re.search(r"heading\s*([1-9])", value, flags=re.IGNORECASE)
        return int(match.group(1)) if match else 0

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                document_xml = package.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile, OSError) as exc:
            raise DocumentParserError("PARSER_DOCX_INVALID", "DOCX package is invalid or missing word/document.xml") from exc
        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as exc:
            raise DocumentParserError("PARSER_DOCX_INVALID", "DOCX XML document is invalid") from exc

        blocks: list[ParsedBlock] = []
        body = root.find("./w:body", self._NS)
        if body is None:
            raise DocumentParserError("PARSER_DOCX_INVALID", "DOCX body is missing")
        for child in list(body):
            local = str(child.tag).rsplit("}", 1)[-1]
            if local == "p":
                text = self._paragraph_text(child)
                if not text:
                    continue
                level = self._heading_level(child)
                rendered = f"{'#' * level} {text}" if level else text
                blocks.append(ParsedBlock(rendered, "heading" if level else "paragraph", {"paragraph": len(blocks) + 1}))
            elif local == "tbl":
                for row_index, row in enumerate(child.findall("./w:tr", self._NS), start=1):
                    cells: list[str] = []
                    for cell in row.findall("./w:tc", self._NS):
                        paragraphs = [
                            self._paragraph_text(paragraph)
                            for paragraph in cell.findall("./w:p", self._NS)
                        ]
                        cells.append(" ".join(value for value in paragraphs if value).strip())
                    row_text = " | ".join(cells).strip()
                    if row_text:
                        blocks.append(ParsedBlock(row_text, "table_row", {"row": row_index}))
        text = "\n\n".join(block.text for block in blocks)
        return ParsedDocument(
            self.format_name,
            text,
            tuple(blocks),
            {},
            self.parser_name,
            self.parser_version,
            parse_status="parsed" if text else "degraded",
            warnings=() if text else ("docx_text_extraction_empty",),
        )


def _format_from_inputs(content: bytes, filename: str, content_type: str) -> str:
    normalized_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    mime_format = _MIME_FORMATS.get(normalized_mime, "")
    lowered = str(filename or "").lower()
    extension = next((suffix for suffix in _EXTENSION_FORMATS if lowered.endswith(suffix)), "")
    extension_format = _EXTENSION_FORMATS.get(extension, "")
    if mime_format and extension_format and mime_format != extension_format:
        # Generic text/plain is compatible with CLI/config extensions; the
        # extension still determines the richer structured parser contract.
        if not ({mime_format, extension_format} <= {"txt", "config"}):
            raise DocumentParserError("PARSER_FORMAT_MISMATCH", "Filename extension and content type disagree")
    if content.startswith(b"%PDF-"):
        detected = "pdf"
        if (mime_format and mime_format != "pdf") or (extension_format and extension_format != "pdf"):
            raise DocumentParserError("PARSER_FORMAT_MISMATCH", "PDF magic does not match the declared file format")
    else:
        detected = extension_format if (mime_format and extension_format and mime_format != extension_format) else (mime_format or extension_format)
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
            "json": JsonParserAdapter(),
            "yaml": YamlParserAdapter(),
            "csv": CsvParserAdapter(),
            "xml": XmlParserAdapter(),
            "config": ConfigParserAdapter(),
            "pdf": PdfParserAdapter(),
            "docx": DocxParserAdapter(),
        })
        if set(self._adapters) != set(SUPPORTED_FORMATS):
            raise DocumentParserError("PARSER_REGISTRY_INVALID", "Parser registry must provide one adapter per supported format")

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
    """Parse through the canonical text/PDF/DOCX registry."""
    return document_parser_registry.parse(content, filename=filename, content_type=content_type)


__all__ = [
    "DocumentParserAdapter",
    "DocumentParserError",
    "DocumentParserRegistry",
    "ConfigParserAdapter",
    "CsvParserAdapter",
    "DocxParserAdapter",
    "HtmlParserAdapter",
    "JsonParserAdapter",
    "MarkdownParserAdapter",
    "ParsedBlock",
    "ParsedDocument",
    "PdfParserAdapter",
    "TxtParserAdapter",
    "XmlParserAdapter",
    "YamlParserAdapter",
    "document_parser_registry",
    "parse_document",
]
