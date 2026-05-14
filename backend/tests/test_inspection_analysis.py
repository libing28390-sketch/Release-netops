"""
Tests for inspection analysis functions.
Task 1.1: Verify summarize_run_analysis() reads from analysis_json field correctly.
"""
import json
import pytest
from backend.core.analysis import summarize_run_analysis


def test_summarize_run_analysis_reads_analysis_json():
    """R1.1: summarize_run_analysis should read from analysis_json field, not analysis."""
    device_results = [
        {
            "device_id": "dev-1",
            "analysis_json": json.dumps([
                {"metric": "CPU利用率", "key": "cpu", "value": 90, "status": "critical",
                 "conclusion": "严重超标", "suggestion": "检查进程"},
                {"metric": "内存利用率", "key": "mem", "value": 75, "status": "warning",
                 "conclusion": "告警", "suggestion": "关注趋势"},
            ]),
        },
        {
            "device_id": "dev-2",
            "analysis_json": json.dumps([
                {"metric": "CPU利用率", "key": "cpu", "value": 20, "status": "healthy",
                 "conclusion": "正常", "suggestion": ""},
            ]),
        },
    ]

    summary = summarize_run_analysis(device_results)

    assert summary["total_anomalies"] == 2
    assert summary["critical_count"] == 1
    assert summary["warning_count"] == 1
    # CPU利用率 appears in both devices (1 critical + 1 healthy), only anomalies counted
    assert any(issue["metric"] == "CPU利用率" for issue in summary["top_issues"])


def test_summarize_run_analysis_ignores_legacy_analysis_field():
    """R1.1: The old 'analysis' field should be ignored; only analysis_json is used."""
    device_results = [
        {
            "device_id": "dev-1",
            # Old field - should be ignored
            "analysis": [
                {"metric": "CPU利用率", "key": "cpu", "value": 90, "status": "critical",
                 "conclusion": "严重超标", "suggestion": "检查进程"},
            ],
            # New field - should be used (empty)
            "analysis_json": json.dumps([]),
        },
    ]

    summary = summarize_run_analysis(device_results)

    # Should read from analysis_json (empty), not from analysis field
    assert summary["total_anomalies"] == 0
    assert summary["critical_count"] == 0


def test_summarize_run_analysis_handles_null_analysis_json():
    """R1.1: NULL analysis_json should be treated as empty list, not raise exception."""
    device_results = [
        {"device_id": "dev-1", "analysis_json": None},
        {"device_id": "dev-2"},  # missing key entirely
    ]

    summary = summarize_run_analysis(device_results)

    assert summary["total_anomalies"] == 0
    assert "conclusion" in summary


def test_summarize_run_analysis_top_issues_ordering():
    """R1.1: top_issues should be sorted by count descending, max 3 items."""
    device_results = [
        {
            "device_id": f"dev-{i}",
            "analysis_json": json.dumps([
                {"metric": "CPU利用率", "key": "cpu", "value": 90, "status": "critical",
                 "conclusion": "超标", "suggestion": ""},
                {"metric": "内存利用率", "key": "mem", "value": 80, "status": "warning",
                 "conclusion": "告警", "suggestion": ""},
                {"metric": "接口错误", "key": "intf_err", "value": 50, "status": "warning",
                 "conclusion": "告警", "suggestion": ""},
                {"metric": "温度", "key": "temp", "value": 70, "status": "critical",
                 "conclusion": "超标", "suggestion": ""},
            ]),
        }
        for i in range(3)
    ]

    summary = summarize_run_analysis(device_results)

    assert len(summary["top_issues"]) <= 3
    # Verify descending order
    counts = [issue["count"] for issue in summary["top_issues"]]
    assert counts == sorted(counts, reverse=True)
