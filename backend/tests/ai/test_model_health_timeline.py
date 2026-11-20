from datetime import date

from ai.services.model_health import build_health_timeline, classify_health_bucket


def test_classify_health_bucket_keeps_missing_data_unknown() -> None:
    assert classify_health_bucket(0, 0) == "unknown"
    assert classify_health_bucket(10, 10) == "healthy"
    assert classify_health_bucket(100, 99) == "degraded"
    assert classify_health_bucket(10, 9) == "unhealthy"


def test_build_health_timeline_fills_days_without_samples() -> None:
    timeline = build_health_timeline(
        {
            "2026-09-09": (10, 10, 240),
            "2026-09-10": (10, 9, 280),
        },
        start_date=date(2026, 9, 8),
        end_date=date(2026, 9, 10),
    )

    assert [point["status"] for point in timeline] == ["unknown", "healthy", "unhealthy"]
    assert timeline[1]["availability_percent"] == 100.0
    assert timeline[2]["failure_count"] == 1
    assert timeline[2]["avg_latency_ms"] == 280
