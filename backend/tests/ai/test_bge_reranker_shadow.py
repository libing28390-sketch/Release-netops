import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from ai.services.retrieval_contract import (
    BoundedReranker,
    RemoteSidecarReranker,
    Reranker,
)
from reranker_sidecar.app import engine as local_sidecar_engine
from reranker_sidecar.app import _verify_auth as verify_sidecar_auth


def test_bge_sidecar_engine_lexical_semantic_ranking():
    """验证独立 Sidecar 本地评分引擎能够正确打分并按相关性排序。"""
    query = "configure vlan 10 on cisco switch"
    candidates = [
        {"candidate_id": "doc-unrelated", "text": "display bgp peer on huawei router"},
        {"candidate_id": "doc-vlan", "text": "cisco switch vlan 10 configuration switchport access"},
    ]
    results = local_sidecar_engine.rerank(query, candidates)
    assert len(results) == 2
    assert results[0]["candidate_id"] == "doc-vlan"
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["rank"] == 1


def test_bge_sidecar_requires_configured_internal_token(monkeypatch):
    """The sidecar must fail closed when its deployment secret is absent or wrong."""
    from fastapi import HTTPException

    monkeypatch.delenv("BGE_API_KEY", raising=False)
    with pytest.raises(HTTPException) as missing:
        verify_sidecar_auth(None)
    assert missing.value.status_code == 503

    monkeypatch.setenv("BGE_API_KEY", "test-only-sidecar-token")
    with pytest.raises(HTTPException) as wrong:
        verify_sidecar_auth("wrong-token")
    assert wrong.value.status_code == 401
    assert verify_sidecar_auth("test-only-sidecar-token") is None


def test_bounded_reranker_legacy_mode():
    """验证 legacy 模式：直接保留原有排序，不调用深度重排。"""
    candidates = [
        {"document_id": "doc-1", "relevance_score": 0.9},
        {"document_id": "doc-2", "relevance_score": 0.8},
    ]
    reranker = BoundedReranker(Reranker(), mode="legacy")
    res, debug = reranker.apply("test query", candidates)
    assert res == candidates
    assert debug["stage"] == "legacy_pass"
    assert debug["mode"] == "legacy"


def test_bounded_reranker_shadow_mode_preserves_baseline_and_observes_delta():
    """
    验证 Shadow 模式核心契约：
    1. 返回给调用方/用户的排序严格保持与输入 baseline 一致（保证生产绝对安全）；
    2. debug 字典记录 shadow_top_ids 和 baseline_top_ids 的差异观察。
    """
    candidates = [
        {"document_id": "doc-baseline-1", "relevance_score": 0.85, "source_trust_rank": 1},
        {"document_id": "doc-baseline-2", "relevance_score": 0.75, "source_trust_rank": 1},
    ]

    class ReverseReranker:
        name = "mock-reverse"
        def rank(self, query, items):
            # 故意将第二个候选人评为最高分
            return [0.1, 1.0]

    bounded = BoundedReranker(ReverseReranker(), mode="shadow")
    res, debug = bounded.apply("query", candidates)

    # 关键断言 1：返回结果必须保持输入 baseline，绝不能被影子重排掉换！
    assert res[0]["document_id"] == "doc-baseline-1"
    assert res[1]["document_id"] == "doc-baseline-2"

    # 关键断言 2：影子观察记录了反转后的真实情况
    assert debug["stage"] == "shadow_observed"
    assert debug["mode"] == "shadow"
    assert debug["shadow_top_ids"] == ["doc-baseline-2", "doc-baseline-1"]
    assert debug["baseline_top_ids"] == ["doc-baseline-1", "doc-baseline-2"]
    assert debug["order_changed"] is True


def test_bounded_reranker_active_mode_applies_new_order():
    """验证 active 模式：在验证通过后，生产切流返回最新重排结果。"""
    candidates = [
        {"document_id": "doc-baseline-1", "relevance_score": 0.80, "source_trust_rank": 1},
        {"document_id": "doc-baseline-2", "relevance_score": 0.70, "source_trust_rank": 1},
    ]

    class BetterReranker:
        name = "mock-better"
        def rank(self, query, items):
            return [0.1, 0.95]

    bounded = BoundedReranker(BetterReranker(), mode="active")
    res, debug = bounded.apply("query", candidates)

    assert debug["stage"] == "applied"
    assert debug["mode"] == "active"
    # doc-baseline-2 得到高分后逆袭至第一名
    assert res[0]["document_id"] == "doc-baseline-2"


def test_remote_sidecar_reranker_connection_error_gracefully_degrades():
    """验证当外部 Sidecar 服务不可达时，RemoteSidecarReranker 配合 BoundedReranker 平滑降级。"""
    # 模拟指向一个不可用的端口
    remote = RemoteSidecarReranker(endpoint="http://127.0.0.1:59999/v1/rerank", timeout_seconds=0.1)
    candidates = [
        {"document_id": "doc-1", "relevance_score": 0.9},
        {"document_id": "doc-2", "relevance_score": 0.8},
    ]

    bounded = BoundedReranker(remote, timeout_ms=200, mode="active")
    res, debug = bounded.apply("query", candidates)

    # 验证降级保活：无 500 异常，完整返回基础候选集
    assert res == candidates
    assert debug["stage"] == "degraded"
    assert debug["reason"] in {"reranker_error", "timeout"}


def test_remote_sidecar_reranker_rejects_unsafe_endpoint_and_response(monkeypatch):
    """Sidecar HTTP boundaries reject non-HTTP endpoints and malformed IDs/scores."""
    import ai.services.retrieval_contract as contract

    with pytest.raises(ValueError):
        RemoteSidecarReranker(endpoint="ftp://127.0.0.1:8004/v1/rerank")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"results": [{"candidate_id": "ghost", "score": 2.0}]}).encode()

    monkeypatch.setattr(contract.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    remote = RemoteSidecarReranker(endpoint="http://127.0.0.1:8004/v1/rerank")
    with pytest.raises(ValueError):
        remote.rank("query", [{"document_id": "doc-1", "content": "text"}])


def test_reranker_timeout_pool_has_a_finite_thread_bound():
    """Repeated hung calls must not create one daemon thread per request."""
    class HungReranker:
        name = "hung-test"

        def rank(self, _query, _candidates):
            time.sleep(0.25)
            return [0.0]

    bounded = BoundedReranker(HungReranker(), timeout_ms=1, mode="active")
    candidates = [{"document_id": "doc-1", "relevance_score": 0.1}]
    for _ in range(24):
        bounded.apply("query", candidates)

    time.sleep(0.01)
    worker_names = [thread.name for thread in threading.enumerate() if thread.name.startswith("ret-rerank-")]
    assert len(worker_names) <= 4
