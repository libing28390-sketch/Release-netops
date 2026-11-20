from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest


def test_ing006_registry_exposes_one_contract_for_all_supported_formats():
    from services.document_parser_adapters import document_parser_registry

    assert document_parser_registry.formats() == ("html", "markdown", "txt", "json", "yaml", "csv", "xml", "config", "pdf", "docx")
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


def test_ing006_docx_adapter_extracts_headings_paragraphs_and_table_rows():
    from services.document_parser_adapters import parse_document

    document_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>VLAN Guide</w:t></w:r></w:p>
        <w:p><w:r><w:t>switchport mode access</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Port</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>VLAN</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>'''
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document_xml)
    result = parse_document(
        payload.getvalue(),
        filename="guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert result.format == "docx"
    assert result.text.splitlines()[0] == "# VLAN Guide"
    assert "switchport mode access" in result.text
    assert "Port | VLAN" in result.text
    assert [block.block_type for block in result.blocks] == ["heading", "paragraph", "table_row"]


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


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "format_name", "marker"),
    [
        ("inventory.json", "application/json", b'{"hostname":"sw-1","vendor":"Huawei"}', "json", '"hostname": "sw-1"'),
        ("inventory.yaml", "application/yaml", b"hostname: sw-1\nvendor: Huawei\n", "yaml", "hostname: sw-1"),
        ("inventory.csv", "text/csv", b"hostname,vendor\nsw-1,Huawei\n", "csv", "sw-1 | Huawei"),
        ("inventory.xml", "application/xml", b"<device><hostname>sw-1</hostname><vendor>Huawei</vendor></device>", "xml", "sw-1"),
        ("running.conf", "text/plain", b"system-view\nvlan 10\n", "config", "vlan 10"),
    ],
)
def test_ing006_structured_formats_are_validated_and_normalized(filename, content_type, body, format_name, marker):
    from services.document_parser_adapters import parse_document

    result = parse_document(body, filename=filename, content_type=content_type)
    assert result.format == format_name
    assert marker in result.text
    assert result.metadata["structured_format"] == format_name


def test_ing006_custom_json_document_envelope_separates_metadata_from_body():
    from ai.services.knowledge_source_parser import parse_knowledge_source

    body = """{
      "format": "nexora-knowledge-document",
      "schema_version": "2.0",
      "metadata": {
        "document_id": "custom.cisco.vlan.v1",
        "title": "Cisco VLAN",
        "vendor": "Cisco",
        "product_type": "network_switch",
        "document_category": "configuration",
        "source_type": "user_document",
        "official_only": false,
        "status": "draft"
      },
      "content": "# Cisco VLAN\\n\\ninterface GigabitEthernet1/0/1"
    }"""

    parsed = parse_knowledge_source(body, filename="custom.json")
    assert parsed.metadata_parse_status == "parsed"
    assert parsed.metadata["document_id"] == "custom.cisco.vlan.v1"
    assert parsed.metadata["schema_version"] == "2.0"
    assert parsed.content.startswith("# Cisco VLAN")
    assert parsed.parser_name == "nexora-json-document-envelope"
    assert "structured_document_envelope" in parsed.warnings


def test_ing006_custom_yaml_document_envelope_rejects_missing_body():
    from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source

    with pytest.raises(KnowledgeSourceParseError) as exc:
        parse_knowledge_source(
            "format: nexora-knowledge-document\nschema_version: '2.0'\nmetadata: {}\ncontent:\n",
            filename="custom.yaml",
        )
    assert exc.value.code == "PARSER_DOCUMENT_ENVELOPE_INVALID"


def test_ing006_published_custom_templates_are_parseable():
    from ai.services.knowledge_document_contract import json_template, markdown_template
    from ai.services.knowledge_source_parser import parse_knowledge_source

    markdown = parse_knowledge_source(markdown_template(), filename="template.md")
    assert markdown.metadata["schema_version"] == "2.0"
    assert markdown.metadata["document_id"] == "custom.huawei.s5735.vlan.v1"
    assert "配置步骤" in markdown.content

    envelope = parse_knowledge_source(json_template(), filename="template.json")
    assert envelope.metadata_parse_status == "parsed"
    assert envelope.metadata["vendor"] == "Huawei"
    assert "vlan batch 10" in envelope.content


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "code"),
    [
        ("inventory.json", "application/json", b"{bad", "PARSER_JSON_INVALID"),
        ("inventory.yaml", "application/yaml", b"a: [", "PARSER_YAML_INVALID"),
        ("inventory.xml", "application/xml", b"<device>", "PARSER_XML_INVALID"),
    ],
)
def test_ing006_structured_format_errors_are_fail_closed(filename, content_type, body, code):
    from services.document_parser_adapters import DocumentParserError, parse_document

    with pytest.raises(DocumentParserError) as exc:
        parse_document(body, filename=filename, content_type=content_type)
    assert exc.value.code == code


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
