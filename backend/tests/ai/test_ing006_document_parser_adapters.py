from __future__ import annotations

from pathlib import Path

import pytest


def test_ing006_registry_exposes_one_contract_for_all_four_formats():
    from services.document_parser_adapters import document_parser_registry

    assert document_parser_registry.formats() == ("html", "markdown", "txt", "pdf")
    for format_name in document_parser_registry.formats():
        adapter = document_parser_registry.get(format_name)
        assert adapter.format_name == format_name
        assert adapter.parser_name.startswith("nexora-")
        assert adapter.parser_version
        assert callable(adapter.parse)


def test_ing006_ai_namespace_reexports_canonical_registry():
    from ai.services.document_parser_adapters import parse_document

    assert parse_document(b"hello", filename="a.txt", content_type="text/plain").format == "txt"


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "format_name"),
    [
        ("guide.txt", "text/plain", b"line one\r\nline two", "txt"),
        ("guide.md", "text/markdown", b"# Heading\n\nBody", "markdown"),
        ("guide.html", "text/html", b"<h1>Heading</h1><p>Body</p>", "html"),
        ("guide.pdf", "application/pdf", b"%PDF-1.4\nBT\n(Body) Tj\nET\n%%EOF", "pdf"),
    ],
)
def test_ing006_all_adapters_return_same_bounded_result_contract(filename, content_type, body, format_name):
    from services.document_parser_adapters import parse_document

    result = parse_document(body, filename=filename, content_type=content_type)
    assert result.format == format_name
    assert result.parser_name.startswith("nexora-")
    assert result.parser_version == "1.0.0"
    assert result.parse_status in {"parsed", "degraded"}
    assert isinstance(result.blocks, tuple)
    public = result.as_dict()
    assert "text" not in public
    assert set(public) == {"format", "blocks", "metadata", "parser_name", "parser_version", "parse_status", "warnings"}


def test_ing006_txt_normalizes_line_endings_and_records_line_locators():
    from services.document_parser_adapters import parse_document

    result = parse_document(b"a\r\nb\rc\n", filename="guide.txt", content_type="text/plain")
    assert result.text == "a\nb\nc\n"
    assert [block.locator["line_start"] for block in result.blocks] == [1, 2, 3]


def test_ing006_markdown_uses_existing_front_matter_contract_without_indexing_header():
    from services.document_parser_adapters import parse_document

    body = b"---\nschema_version: '2.0'\ndocument_id: doc-1\ntitle: Guide\nvendor: Cisco\nproduct_type: switch\ndocument_category: command\nsource_type: official\nofficial_only: true\nstatus: active\n---\n\nshow version"
    result = parse_document(body, filename="guide.md", content_type="text/markdown")
    assert result.metadata["document_id"] == "doc-1"
    assert result.text.strip() == "show version"
    assert all("schema_version" not in block.text for block in result.blocks)


def test_ing006_markdown_malformed_front_matter_is_stable_error():
    from services.document_parser_adapters import DocumentParserError, parse_document

    with pytest.raises(DocumentParserError) as exc:
        parse_document(b"---\n: invalid: [\n---\nbody", filename="guide.md", content_type="text/markdown")
    assert exc.value.code == "PARSER_MARKDOWN_FRONT_MATTER_INVALID"
    assert "invalid" not in str(exc.value).lower() or "yaml" not in str(exc.value).lower()


def test_ing006_html_extracts_structural_blocks_and_marks_later_cleaning_stage():
    from services.document_parser_adapters import parse_document

    result = parse_document(b"<h1>Title</h1><nav>Menu</nav><p>Body &amp; detail</p><script>prompt('x')</script>", filename="guide.html", content_type="text/html")
    assert [block.block_type for block in result.blocks] == ["heading", "paragraph", "paragraph"]
    assert "Body & detail" in result.text
    assert "prompt" not in result.text
    assert "html_requires_ing007_content_cleaning" in result.warnings


def test_ing006_pdf_adapter_uses_safe_fallback_for_simple_text_operators():
    from services.document_parser_adapters import parse_document

    result = parse_document(b"%PDF-1.4\nBT\n(Hello \\(network\\)) Tj\n(Guide) Tj\nET\n%%EOF", filename="guide.pdf", content_type="application/pdf")
    assert "Hello (network)" in result.text
    assert "Guide" in result.text
    assert result.metadata["page_count"] == 0


@pytest.mark.parametrize(
    ("body", "filename", "content_type", "code"),
    [
        (b"", "guide.txt", "text/plain", "PARSER_EMPTY_DOCUMENT"),
        (b"x", "guide.pdf", "application/pdf", "PARSER_PDF_MAGIC_INVALID"),
        (b"x", "guide.bin", "application/octet-stream", "PARSER_FORMAT_UNSUPPORTED"),
        (b"<p>x</p>", "guide.pdf", "application/pdf", "PARSER_PDF_MAGIC_INVALID"),
        (b"%PDF-1.4", "guide.txt", "text/plain", "PARSER_FORMAT_MISMATCH"),
    ],
)
def test_ing006_format_and_empty_failures_are_fail_closed(body, filename, content_type, code):
    from services.document_parser_adapters import DocumentParserError, parse_document

    with pytest.raises(DocumentParserError) as exc:
        parse_document(body, filename=filename, content_type=content_type)
    assert exc.value.code == code
    assert "\xff" not in str(exc.value)


def test_ing006_rejects_non_utf8_text_and_control_bytes():
    from services.document_parser_adapters import DocumentParserError, parse_document

    with pytest.raises(DocumentParserError) as encoding:
        parse_document(b"\xff\xfe", filename="guide.txt", content_type="text/plain")
    assert encoding.value.code == "PARSER_ENCODING_INVALID"
    with pytest.raises(DocumentParserError) as control:
        parse_document(b"hello\x01world", filename="guide.md", content_type="text/markdown")
    assert control.value.code == "PARSER_CONTROL_BYTES"


def test_ing006_rejects_filename_mime_mismatch_and_size_without_allocating_result():
    from services.document_parser_adapters import DocumentParserError, MAX_PARSE_BYTES, parse_document

    with pytest.raises(DocumentParserError) as mismatch:
        parse_document(b"<p>x</p>", filename="guide.md", content_type="text/html")
    assert mismatch.value.code == "PARSER_FORMAT_MISMATCH"
    with pytest.raises(DocumentParserError) as large:
        parse_document(b"x" * (MAX_PARSE_BYTES + 1), filename="guide.txt", content_type="text/plain")
    assert large.value.code == "PARSER_DOCUMENT_TOO_LARGE"


def test_ing006_registry_and_adapters_have_no_network_client_imports():
    source = Path("backend/services/document_parser_adapters.py").read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "socket" not in source
    assert "requests" not in source
