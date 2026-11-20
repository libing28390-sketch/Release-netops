from __future__ import annotations

import json
import threading
import time

import pytest
from services.document_parser_adapters import (
    DoclingParserAdapter,
    DocumentParserError,
    DualTrackParserAdapter,
    ParsedBlock,
    ParsedDocument,
    PdfParserAdapter,
)


class MockNativeParser:
    format_name = "pdf"
    parser_name = "nexora-pdf"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        return ParsedDocument(
            format="pdf",
            text="Native extracted text line 1\nNative extracted text line 2",
            blocks=(ParsedBlock(text="Native extracted text", block_type="pdf_text", locator={"line_start": 1, "line_end": 2}),),
            metadata={"page_count": 2},
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            parse_status="parsed",
            warnings=(),
        )


class MockSuccessfulDoclingParser:
    format_name = "docling"
    parser_name = "docling-parser"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        return ParsedDocument(
            format="pdf",
            text="# Docling Section\n| Port | VLAN |\n| Eth1/1 | 10 |",
            blocks=(
                ParsedBlock(text="# Docling Section", block_type="docling_markdown", locator={"line_start": 1, "line_end": 1}),
                ParsedBlock(text="| Port | VLAN |", block_type="docling_markdown", locator={"line_start": 2, "line_end": 3}),
            ),
            metadata={"page_count": 2, "docling_version": "2.0"},
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            parse_status="parsed",
            warnings=(),
        )


class MockFailingDoclingParser:
    format_name = "docling"
    parser_name = "docling-parser"
    parser_version = "1.0.0"

    def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
        raise RuntimeError("Docling container unreachable or timeout")


def test_dual_track_parser_legacy_mode():
    """验证 legacy 模式：只执行原有自研解析器，元数据不包含 shadow 观察。"""
    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=MockSuccessfulDoclingParser(), mode="legacy")
    res = adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    assert res.parser_name == "nexora-pdf"
    assert "Native extracted text" in res.text
    assert "shadow_docling" not in res.metadata


def test_dual_track_parser_shadow_mode_observes_without_modifying_output():
    """
    验证 Shadow 模式核心契约：
    1. 返回内容和 blocks 100% 由原有原生解析器决定（保证生产完全稳定安全）；
    2. 元数据中附加 shadow_docling 统计指标（字数、块数、状态）。
    """
    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=MockSuccessfulDoclingParser(), mode="shadow")
    res = adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    # 100% 保持原生文本输出给生产
    assert "Native extracted text" in res.text
    assert res.parser_name == "nexora-pdf"

    # 影子元数据成功采集
    shadow_meta = res.metadata.get("shadow_docling", {})
    assert shadow_meta.get("shadow_status") == "observed"
    assert shadow_meta.get("docling_char_count") > 0
    assert shadow_meta.get("docling_block_count") == 2
    assert shadow_meta.get("docling_parse_status") == "parsed"


def test_dual_track_parser_shadow_mode_resilient_to_docling_failure():
    """验证当 Docling 发生异常时，Shadow 模式静默捕获，原生解析依然正常返回。"""
    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=MockFailingDoclingParser(), mode="shadow")
    res = adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    assert "Native extracted text" in res.text
    shadow_meta = res.metadata.get("shadow_docling", {})
    assert shadow_meta.get("shadow_status") == "degraded"
    assert "RuntimeError" in shadow_meta.get("docling_error", "")


def test_dual_track_parser_docling_mode_fails_safe_to_primary():
    """验证当处于 docling 灰度模式时，一旦 Docling 失败，100% 平滑降级至原生解析器。"""
    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=MockFailingDoclingParser(), mode="docling")
    res = adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    # 自动降级为原生解析结果
    assert res.parser_name == "nexora-pdf"
    assert "Native extracted text" in res.text


def test_dual_track_parser_docling_mode_switches_when_successful():
    """验证当处于 docling 灰度模式且成功时，生产切流使用 Docling 高质量解析。"""
    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=MockSuccessfulDoclingParser(), mode="docling")
    res = adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    assert res.parser_name == "docling-parser"
    assert "# Docling Section" in res.text
    assert len(res.blocks) == 2


def test_docling_parser_adapter_not_configured_raises_expected_error():
    """验证未配置 AI_DOCLING_BASE_URL 时，DoclingParserAdapter 抛出符合契约的错误码。"""
    adapter = DoclingParserAdapter(base_url="")
    with pytest.raises(DocumentParserError) as exc_info:
        adapter.parse(b"dummy", filename="sample.pdf")
    assert exc_info.value.code == "DOCLING_NOT_CONFIGURED"


def test_docling_parser_rejects_unsafe_endpoint_and_malformed_response(monkeypatch):
    import services.document_parser_adapters as adapters

    with pytest.raises(DocumentParserError) as endpoint_error:
        DoclingParserAdapter(base_url="ftp://127.0.0.1:8005")
    assert endpoint_error.value.code == "DOCLING_INVALID_ENDPOINT"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"page_count": "not-a-number", "markdown": "# bad"}).encode()

    monkeypatch.setattr(adapters.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(DocumentParserError) as response_error:
        DoclingParserAdapter(base_url="http://127.0.0.1:8005").parse(b"pdf", filename="sample.pdf")
    assert response_error.value.code == "DOCLING_RESPONSE_INVALID"


def test_docling_shadow_pool_has_a_finite_thread_bound():
    class SlowDoclingParser(MockFailingDoclingParser):
        def parse(self, content: bytes, *, filename: str = "", content_type: str = "") -> ParsedDocument:
            time.sleep(0.25)
            return super().parse(content, filename=filename, content_type=content_type)

    adapter = DualTrackParserAdapter(primary=MockNativeParser(), docling=SlowDoclingParser(), mode="shadow")
    for _ in range(20):
        adapter.parse(b"%PDF-1.4...", filename="guide.pdf")

    time.sleep(0.01)
    worker_names = [thread.name for thread in threading.enumerate() if thread.name.startswith("docling-shadow-")]
    assert len(worker_names) <= 2
