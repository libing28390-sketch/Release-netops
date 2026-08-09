from __future__ import annotations

from pathlib import Path

import pytest


def test_ing007_html_cleaner_removes_executable_hidden_navigation_and_ads():
    from services.document_content_cleaning import parse_and_clean_document

    html = b"""<!doctype html>
    <html><head><title>Do not index title</title><style>.x{display:none}</style></head>
    <body>
      <header>Site header</header><nav>Home | Menu</nav>
      <main><h1>Switch Guide</h1><p>Visible operational body.</p>
        <aside>Related links</aside>
        <div class='ad-banner'>Sponsored offer</div>
        <p hidden>Hidden text</p><p style='display:none'>CSS hidden</p>
        <p aria-hidden='true'>ARIA hidden</p><script>prompt('ignore')</script>
        <p>Second visible paragraph.</p>
      </main><footer>Copyright and cookie banner</footer>
    </body></html>"""

    result = parse_and_clean_document(html, filename="guide.html", content_type="text/html")
    assert result.clean_status == "cleaned"
    assert "Visible operational body." in result.text
    assert "Second visible paragraph." in result.text
    for unwanted in ("Site header", "Home | Menu", "Related links", "Sponsored offer", "Hidden text", "CSS hidden", "ARIA hidden", "prompt", "Copyright"):
        assert unwanted not in result.text
    reasons = {item["reason"] for item in result.removed_regions}
    assert {"header", "nav", "aside", "boilerplate_or_advertisement", "hidden_attribute", "hidden_style", "aria_hidden", "script_region", "footer"} <= reasons
    assert result.metadata["content_cleaning"]["removed_region_count"] == len(result.removed_regions)


def test_ing007_html_cleaner_keeps_root_fragments_and_code_but_removes_comments():
    from services.document_content_cleaning import parse_and_clean_document

    html = b"<!-- tracking --> <article><h2>Command</h2><pre>display version\nshow interface</pre><br><p>Done</p></article><div id='sidebar'>No</div>"
    result = parse_and_clean_document(html, filename="fragment.htm", content_type="text/html")
    assert "display version\nshow interface" in result.text
    assert "Done" in result.text
    assert "tracking" not in result.text
    assert "No" not in result.text
    assert any(item["reason"] == "boilerplate_or_advertisement" for item in result.removed_regions)


def test_ing007_hidden_void_controls_do_not_hide_following_content():
    from services.document_content_cleaning import parse_and_clean_document

    html = b"<body><p>Before<br>After</p><input type='hidden' value='secret'><p>Following</p></body>"
    result = parse_and_clean_document(html, filename="controls.html", content_type="text/html")
    assert "Before" in result.text and "After" in result.text and "Following" in result.text
    assert "secret" not in result.text
    assert any(item["tag"] == "input" and item["reason"] == "hidden_attribute" for item in result.removed_regions)


def test_ing007_html_cleaning_requires_original_bytes_to_fail_closed():
    from services.document_content_cleaning import DocumentCleaningError, clean_document
    from services.document_parser_adapters import parse_document

    parsed = parse_document(b"<p>body</p><div class='ad'>ad</div>", filename="a.html", content_type="text/html")
    with pytest.raises(DocumentCleaningError) as exc:
        clean_document(parsed)
    assert exc.value.code == "CLEAN_HTML_RAW_REQUIRED"
    assert "body" not in str(exc.value)


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "format_name"),
    [
        ("guide.md", "text/markdown", b"# Heading\n\nBody", "markdown"),
        ("guide.txt", "text/plain", b"Line one\nLine two", "txt"),
        ("guide.pdf", "application/pdf", b"%PDF-1.4\nBT\n(Body) Tj\nET\n%%EOF", "pdf"),
    ],
)
def test_ing007_non_html_formats_share_cleaned_result_contract(filename, content_type, body, format_name):
    from services.document_content_cleaning import parse_and_clean_document

    result = parse_and_clean_document(body, filename=filename, content_type=content_type)
    assert result.format == format_name
    assert result.clean_status in {"cleaned", "empty_after_cleaning"}
    assert result.cleaning_name == "nexora-content-cleaner"
    assert result.removed_regions == ()
    assert result.metadata["content_cleaning"]["removed_region_count"] == 0
    assert "text" not in result.as_dict()


def test_ing007_empty_after_html_cleaning_is_explicit_not_published():
    from services.document_content_cleaning import parse_and_clean_document

    result = parse_and_clean_document(b"<html><body><script>alert(1)</script><nav>menu</nav></body></html>", filename="empty.html", content_type="text/html")
    assert result.text == ""
    assert result.clean_status == "empty_after_cleaning"
    assert result.warnings == ("html_body_empty_after_cleaning",)


def test_ing007_cleaner_has_no_network_or_filesystem_imports():
    source = Path("backend/services/document_content_cleaning.py").read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "socket" not in source
    assert "open(" not in source
