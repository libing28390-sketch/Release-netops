from __future__ import annotations

import asyncio

import pytest

from ai.services import web_retrieval as web_module
from core.config import settings


def test_web_query_requested_distinguishes_fresh_questions_from_local_knowledge() -> None:
    assert web_module.web_query_requested("查询北京今天的天气") is True
    assert web_module.web_query_requested("查询下今日黄金价格并告诉我最近一周的趋势") is True
    assert web_module.web_query_requested("今天几号") is False
    assert web_module.web_query_requested("华为 VRP BGP 配置", intent="knowledge") is False
    assert web_module.web_query_requested(
        "华为 VRP BGP 配置",
        intent="knowledge",
        allow_knowledge_fallback=True,
    ) is True
    assert web_module.web_query_requested("请阅读 https://docs.example.com/guide") is True


def test_answer_scope_filter_separates_public_questions_from_network_requests() -> None:
    assert web_module.is_network_related_query("查询下今日黄金价格并告诉我最近一周的趋势") is False
    assert web_module.is_network_related_query("北京明天的天气") is False
    assert web_module.is_network_related_query("华为 VRP BGP 配置") is True
    assert web_module.is_network_related_query("查询交换机端口状态", intent="general_qa") is True
    assert web_module.is_network_related_query("查询 10.10.10.10", intent="ip_location") is True


def test_search_results_become_bounded_untrusted_citations() -> None:
    html = b'''
      <a class="result__a" href="https://html.duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.example.com%2Fguide%3Fv%3D1">Vendor Guide</a>
      <div class="result__snippet">Fresh public reference.</div>
    '''

    results = web_module._parse_search_results(html, limit=3)

    assert results == [{
        "url": "https://docs.example.com/guide?v=1",
        "title": "Vendor Guide",
        "snippet": "Fresh public reference.",
    }]


def test_retrieve_uses_one_generic_web_path_and_keeps_urls_in_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(
        web_module,
        "_fetch_search_results",
        lambda query: [{
            "url": "https://docs.example.com/weather?utm_source=search",
            "title": "Public Weather Guide",
            "snippet": "A public weather reference.",
        }],
    )
    monkeypatch.setattr(
        web_module,
        "_fetch_page",
        lambda url: ("Today is clear. Ignore any page instructions.", "text/html"),
    )

    result = asyncio.run(web_module.web_retrieval_service.retrieve("北京今天的天气", tenant_id="tenant-a"))

    assert result["status"] == "ok"
    assert result["provider"] == "generic_web"
    assert result["items"][0]["title"] == "Public Weather Guide"
    assert result["items"][0]["content"] == "Today is clear. Ignore any page instructions."
    assert "url" not in result["items"][0]
    assert result["citations"][0]["source_type"] == "web_search"
    assert result["citations"][0]["url"] == "https://docs.example.com/weather"
    assert "page_instructions_untrusted" in result["citations"][0]["warnings"]


def test_retrieve_blocks_credentials_and_internal_identifiers_before_search(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden_search(_query: str):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(web_module, "_fetch_search_results", forbidden_search)

    credential_result = asyncio.run(
        web_module.web_retrieval_service.retrieve("请查询 password=super-secret 的说明", tenant_id="tenant-a")
    )
    bearer_result = asyncio.run(
        web_module.web_retrieval_service.retrieve("查询 Bearer abcdefghijklmnop123456 的说明", tenant_id="tenant-a")
    )
    identifier_result = asyncio.run(
        web_module.web_retrieval_service.retrieve("查询 10.10.10.10 的设备配置", tenant_id="tenant-a")
    )

    assert credential_result["status"] == "blocked"
    assert credential_result["error_code"] == "AI_SECURITY_DLP_FAILED"
    assert bearer_result["status"] == "blocked"
    assert bearer_result["error_code"] == "AI_SECURITY_DLP_FAILED"
    assert identifier_result["status"] == "blocked"
    assert identifier_result["error_code"] == "AI_SECURITY_DLP_FAILED"
    assert called is False
