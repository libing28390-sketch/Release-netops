"""Comprehensive unit tests covering all 5 Token Optimization improvements."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from ai.services.assistant import AIAssistantService
from ai.services.local_router import format_context_facts_compact, resolve_local_intent
from core.config import settings


@pytest.fixture(autouse=True)
def _use_legacy_deterministic_bus_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
from ai.services.semantic_cache import (
    _cosine_similarity,
    is_cacheable_query,
    lookup_semantic_cache,
    store_semantic_cache,
)


def test_item1_high_confidence_knowledge_direct_zero_token():
    request = SimpleNamespace(raw_query="H3C S5560X-54F-EI 规格参数是什么", document_category="hardware")
    high_hit = [{"score": 0.91, "content": "固定 48 个千兆口 + 4 个万兆口"}]
    low_hit = [{"score": 0.62, "content": "部分相关内容"}]

    assert AIAssistantService._should_use_cross_platform_retrieval_answer(
        {"request": request, "resolution": {}, "debug": {}},
        high_hit,
    ) is True

    # Low score still synthesizes via LLM
    assert AIAssistantService._should_use_cross_platform_retrieval_answer(
        {"request": request, "resolution": {}, "debug": {}},
        low_hit,
    ) is False

    # Deep explanation / comparison requests still use LLM even with high score
    deep_req = SimpleNamespace(raw_query="对比 H3C 和华为 OSPF 的区别", document_category="hardware")
    assert AIAssistantService._should_use_cross_platform_retrieval_answer(
        {"request": deep_req, "resolution": {}, "debug": {}},
        high_hit,
    ) is False


def test_item2_local_ops_and_explicit_slash_commands_bypass_llm():
    # Explicit slash commands
    for raw, op in (
        ("/ipam 10.10.0.0/24", "ipam_prefix"),
        ("/neighbors S6850-1", "topology_neighbors"),
        ("/interfaces S6850-1", "interface_anomalies"),
        ("/changes S6850-1", "config_changes"),
    ):
        d = resolve_local_intent(raw)
        assert d is not None and d["intent"] in {"local_ops", "module_bus"}
        assert (d["filters"].get("operation") or d["filters"].get("module")) == op
        assert d["parse_status"] == "deterministic"

    alarms = resolve_local_intent("/alarms")
    assert alarms is not None and alarms["intent"] == "alarm_search"

    # Natural language local ops
    for q, op in (
        ("10.10.0.0/24 还有多少可用IP", "ipam_prefix"),
        ("S6850-1 上联连着哪些设备", "topology_neighbors"),
        ("全网哪些端口down了", "interface_anomalies"),
        ("最近配置变更记录有哪些", "config_changes"),
    ):
        d = resolve_local_intent(q)
        assert d is not None and d["intent"] in {"local_ops", "module_bus"}, q
        assert (d["filters"].get("operation") or d["filters"].get("module")) == op

    # CLI/config questions must NOT be hijacked into local_ops
    assert resolve_local_intent("H3C 查看 LLDP 邻居用什么命令") is None
    assert resolve_local_intent("怎么关闭一个物理端口") is None


def test_item3_cost_optimized_router_prefers_local_and_flash_for_lightweight_scenes(monkeypatch):
    from ai.gateway.router import ModelRouter

    class FakeCursor:
        def __init__(self, row):
            self._row = row
        def fetchone(self):
            return self._row

    class FakeConn:
        def __init__(self):
            self.queries = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, sql, params=()):
            self.queries.append(sql)
            if "ai_model_route" in sql:
                return FakeCursor(None)
            if "provider_type" in sql:
                return FakeCursor(("model_local_qwen3b",))
            return FakeCursor(("model_expensive",))

    fake_conn = FakeConn()
    monkeypatch.setattr("ai.gateway.router.get_db_connection", lambda: fake_conn)
    model_id, fallback, reason, _cls = ModelRouter().resolve_route_policy("natural_query")
    assert model_id == "model_local_qwen3b"
    assert reason == "cost_optimized_default"


def test_item4_semantic_cache_guards_and_cosine():
    assert is_cacheable_query("H3C 怎么配置 LACP 链路聚合？", intent="knowledge") is True
    assert is_cacheable_query("今天武汉天气怎么样", intent="general_qa") is False
    assert is_cacheable_query("10.0.0.1 在哪台交换机", intent="knowledge") is False
    assert is_cacheable_query("继续说一下", intent="knowledge", has_history=True) is False
    assert is_cacheable_query("H3C 配置 OSPF", intent="knowledge", web_search=True) is False
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_item5_compact_rag_markdown_cuts_token_overhead():
    verbose_facts = {
        "knowledge_chunks": [
            {
                "chunk_id": "chk_1234567890abcdef",
                "document_id": "doc_1234567890abcdef",
                "document": "H3C Comware V7 LACP 配置指南",
                "vendor": "H3C",
                "cli_platform": "h3c_comware",
                "relevance_score": 0.9123456,
                "vector_score": 0.8812345,
                "lexical_score": 0.7745678,
                "file_path": "/data/knowledge/vendors/h3c/lacp_guide.md",
                "metadata": {"importer": "v2", "risk_level": "r0", "checksum": "abcdef0123456789"},
                "content": "interface Bridge-Aggregation 1\n link-aggregation mode dynamic",
            }
        ]
    }
    raw_json = json.dumps(verbose_facts, ensure_ascii=False)
    compact_md = format_context_facts_compact(verbose_facts)
    assert "H3C Comware V7 LACP 配置指南" in compact_md
    assert "interface Bridge-Aggregation 1" in compact_md
    assert "chunk_id" not in compact_md
    assert "relevance_score" not in compact_md
    assert len(compact_md) < len(raw_json) * 0.65
