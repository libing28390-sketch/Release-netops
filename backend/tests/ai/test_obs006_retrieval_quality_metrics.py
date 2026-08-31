from __future__ import annotations

from ai.services.assistant import AIAssistantService
from ai.services.metrics import AIMetrics
from ai.services.rag_retriever import RetrievalRequest


def test_retrieval_quality_signals_detect_wrong_vendor_version_conflict_and_low_confidence():
    request = RetrievalRequest(
        query="show ospf peer",
        vendor="huawei",
        software_train="vrp",
    )
    quality = AIAssistantService._retrieval_quality_signals(
        request,
        {
            "results": [
                {"vendor": "cisco", "version_score": 0.0, "relevance_score": 0.31},
                {"vendor": "huawei", "version_score": 1.0, "relevance_score": 0.8},
            ],
            "debug": {"version_conflict_count": 2},
        },
    )
    assert quality["no_match"] is False
    assert quality["wrong_vendor_count"] == 1
    assert quality["version_conflict_count"] == 2
    assert quality["low_confidence_count"] == 1
    assert quality["top_relevance_score"] == 0.8
    assert quality["error"] is False


def test_retrieval_metrics_snapshot_exposes_bounded_quality_rates():
    metrics = AIMetrics()
    metrics.retrieval_observed(no_match=True)
    metrics.retrieval_observed(version_conflict=True, low_confidence=True)
    metrics.retrieval_observed(wrong_vendor=True)
    snapshot = metrics.snapshot()["retrieval"]
    assert snapshot == {
        "queries": 3,
        "no_match": 1,
        "no_match_rate": 0.3333,
        "wrong_vendor": 1,
        "version_conflict": 1,
        "low_confidence": 1,
        "errors": 0,
    }


def test_clarification_metrics_are_low_cardinality():
    metrics = AIMetrics()
    metrics.clarification_observed("required", "configuration_reference")
    metrics.clarification_observed("allowed", "configuration_reference")
    metrics.clarification_observed("disabled")
    metrics.clarification_observed("unexpected-status", "raw-user-value")

    assert metrics.snapshot()["clarification"] == {
        "required:configuration_reference": 1,
        "allowed:configuration_reference": 1,
        "disabled:none": 1,
        "unknown:unknown": 1,
    }


def test_retrieval_trace_runtime_quality_projection_is_bounded():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs006",
        user_id="operator",
        query="safe query",
        trace={
            "status": "no_match",
            "runtime": {
                "quality": {
                    "no_match": True,
                    "wrong_vendor_count": 2,
                    "version_conflict_count": 1,
                    "low_confidence_count": 3,
                    "low_confidence_threshold": 0.45,
                    "top_relevance_score": 0.2,
                    "error": False,
                },
            },
        },
    )
    row = get_retrieval_trace(tenant_id="tenant-obs006", trace_id=trace_id)
    assert row is not None
    assert row["runtime"]["quality"]["no_match"] is True
    assert row["runtime"]["quality"]["wrong_vendor_count"] == 2
    assert row["runtime"]["quality"]["top_relevance_score"] == 0.2
