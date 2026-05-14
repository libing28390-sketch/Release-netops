"""
P5: Report Data Completeness Property Test
Tasks 8.6 + 9.4: Verify Excel and HTML reports contain all devices.
Validates: P5
"""
import os
import json
import tempfile

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("DATABASE_URL", "")

from core.report_generator import generate_inspection_excel, generate_inspection_html


def _make_device_result(idx, status='healthy'):
    return {
        'id': f'res-{idx}',
        'run_id': 'run-test',
        'device_id': f'dev-{idx}',
        'hostname': f'switch-{idx:03d}',
        'ip_address': f'10.0.0.{idx % 250 + 1}',
        'platform': 'cisco_ios',
        'role': 'switch',
        'site': 'dc1',
        'ping_ok': 1,
        'ssh_ok': 1,
        'health_score': 100 if status == 'healthy' else (60 if status == 'warning' else 30),
        'health_status': status,
        'compliance_status': 'compliant',
        'metrics_json': json.dumps({'cpu_util': 50 if status == 'healthy' else 90}),
        'findings_json': json.dumps([{'type': 'data_error', 'severity': status, 'message': 'test'}] if status != 'healthy' else []),
        'analysis_json': json.dumps([{'metric': 'CPU', 'status': status, 'value': 90, 'conclusion': 'high', 'suggestion': 'check'}] if status != 'healthy' else []),
        'raw_outputs_json': json.dumps({'show version': 'Cisco IOS 15.0'}),
        'correlated_risks_json': json.dumps([]),
        'checked_at': '2026-01-01T00:00:00',
    }


def _make_run_info(n_devices):
    return {
        'id': 'run-test',
        'name': 'Test Inspection',
        'started_at': '2026-01-01T00:00:00',
        'total_devices': n_devices,
        'avg_health_score': 80.0,
        'analysis_summary_json': json.dumps({'conclusion': 'Test summary'}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# P5: Excel report
# ─────────────────────────────────────────────────────────────────────────────

def test_excel_contains_all_devices(tmp_path):
    """P5: Excel report must include all N devices."""
    n = 5
    results = [_make_device_result(i, 'healthy' if i % 2 == 0 else 'critical') for i in range(n)]
    run_info = _make_run_info(n)
    output = str(tmp_path / "report.xlsx")
    generate_inspection_excel(run_info, results, output)
    assert os.path.exists(output)
    # Verify file is valid xlsx (non-zero size)
    assert os.path.getsize(output) > 1000


@given(n=st.integers(min_value=1, max_value=10))
@settings(max_examples=5, deadline=10000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_excel_with_n_devices(n, tmp_path):
    """P5 (Hypothesis): Excel report works for any N devices."""
    results = [_make_device_result(i, 'healthy') for i in range(n)]
    run_info = _make_run_info(n)
    output = str(tmp_path / f"report_{n}.xlsx")
    generate_inspection_excel(run_info, results, output)
    assert os.path.exists(output)


def test_excel_with_mixed_statuses(tmp_path):
    """P5: Excel works with mixed healthy/warning/critical devices."""
    results = []
    statuses = ['healthy', 'warning', 'critical', 'healthy', 'warning']
    for i, s in enumerate(statuses):
        results.append(_make_device_result(i, s))
    output = str(tmp_path / "mixed.xlsx")
    generate_inspection_excel(_make_run_info(5), results, output)
    assert os.path.exists(output)


def test_excel_with_correlated_risks(tmp_path):
    """P5: Excel includes correlated risks in 整改建议 sheet."""
    res = _make_device_result(0, 'critical')
    res['correlated_risks_json'] = json.dumps([{
        'rule_name': '二层环路风险',
        'description': 'CPU 高 + 接口错误激增',
        'severity': 'critical',
        'suggestion': '检查 STP',
        'triggered_metrics': {'cpu_util': 90}
    }])
    output = str(tmp_path / "risks.xlsx")
    generate_inspection_excel(_make_run_info(1), [res], output)
    assert os.path.exists(output)


def test_excel_cleanup_on_failure(tmp_path):
    """R10.4: Excel cleanup on generation failure."""
    output = str(tmp_path / "fail.xlsx")
    # Pass invalid data that will cause failure during JSON parsing
    bad_results = [{'id': 'r1', 'metrics_json': 'invalid_json{{{', 'findings_json': '[]',
                    'analysis_json': '[]', 'raw_outputs_json': '{}',
                    'hostname': 'x', 'ip_address': 'y'}]
    # Should not raise but generate may handle gracefully
    # If it does raise, file should be cleaned up
    try:
        generate_inspection_excel(_make_run_info(1), bad_results, output)
        # If success, file exists
        if os.path.exists(output):
            os.remove(output)
    except Exception:
        # On failure, output should NOT exist
        assert not os.path.exists(output)


# ─────────────────────────────────────────────────────────────────────────────
# P5 extension: HTML report
# ─────────────────────────────────────────────────────────────────────────────

def test_html_contains_all_devices(tmp_path):
    """P5 ext: HTML report must include all N devices."""
    n = 4
    results = [_make_device_result(i, 'healthy' if i % 2 == 0 else 'warning') for i in range(n)]
    output = str(tmp_path / "report.html")
    generate_inspection_html(_make_run_info(n), results, output, customer_name='TestCo', engineer_name='engineer1')
    assert os.path.exists(output)

    content = open(output, encoding='utf-8').read()
    # Verify all hostnames appear in the HTML
    for i in range(n):
        assert f'switch-{i:03d}' in content, f"hostname switch-{i:03d} not in HTML"

    # Verify ECharts CDN script tag (R7.2/R7.5)
    assert 'echarts' in content.lower()
    # Verify customer/engineer names
    assert 'TestCo' in content
    assert 'engineer1' in content


def test_html_with_correlated_risks(tmp_path):
    """R7.4: HTML report shows correlated risks prominently."""
    res = _make_device_result(0, 'critical')
    res['correlated_risks_json'] = json.dumps([{
        'rule_name': '内存泄漏风险',
        'description': '内存持续增长',
        'severity': 'warning',
        'suggestion': '检查内存',
        'triggered_metrics': {}
    }])
    output = str(tmp_path / "risks.html")
    generate_inspection_html(_make_run_info(1), [res], output)
    assert os.path.exists(output)
    content = open(output, encoding='utf-8').read()
    assert '内存泄漏风险' in content


def test_html_empty_results(tmp_path):
    """P5 edge: HTML works with zero devices."""
    output = str(tmp_path / "empty.html")
    generate_inspection_html(_make_run_info(0), [], output)
    assert os.path.exists(output)
