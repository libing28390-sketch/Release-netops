from __future__ import annotations

from ai.services.metrics import AIMetrics


def test_provider_metrics_project_error_rate_latency_tokens_cost_and_limit_events():
    metrics = AIMetrics()
    metrics.provider_finished(
        "provider-a",
        "model-a",
        status="success",
        latency_ms=20,
        input_tokens=100,
        output_tokens=50,
        estimated_cost=0.0123456,
    )
    metrics.provider_finished(
        "provider-a",
        "model-a",
        status="error",
        latency_ms=80,
        error_code="AI_RATE_LIMIT",
    )
    metrics.limit_event("provider-a", "concurrency_timeout")
    metrics.fallback_event("chat", "provider-a", "model-b", status="started")
    metrics.fallback_event("chat", "provider-a", "model-b", status="success")

    snapshot = metrics.snapshot()
    provider = snapshot["providers"]["provider-a:model-a"]
    assert provider["requests"] == 2
    assert provider["success"] == 1
    assert provider["errors"] == 1
    assert provider["error_rate"] == 0.5
    assert provider["avg_latency_ms"] == 50
    assert provider["p95_latency_ms"] == 20
    assert provider["input_tokens"] == 100
    assert provider["output_tokens"] == 50
    assert provider["estimated_cost_usd"] == 0.012346
    assert snapshot["limits"]["provider-a:AI_RATE_LIMIT"] == 1
    assert snapshot["limits"]["provider-a:concurrency_timeout"] == 1
    assert snapshot["fallbacks"]["chat:provider-a:model-b:started"] == 1
    assert snapshot["fallbacks"]["chat:provider-a:model-b:success"] == 1


def test_provider_metrics_are_low_cardinality_and_bounded():
    metrics = AIMetrics()
    for index in range(1105):
        metrics.provider_finished("provider-b", "model-b", status="success", latency_ms=index)
    snapshot = metrics.snapshot()
    provider = snapshot["providers"]["provider-b:model-b"]
    assert provider["requests"] == 1105
    assert provider["avg_latency_ms"] >= 0
    assert provider["p95_latency_ms"] >= 0
