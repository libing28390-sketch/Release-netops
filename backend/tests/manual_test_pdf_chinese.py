"""
Manual smoke test for PDF Chinese rendering.

Run with:  python -m backend.tests.manual_test_pdf_chinese

This creates a PDF in backend/tests/_out/ and dumps the binary stream
of strings/fonts so we can verify the @font-face + simhei.ttf chain works.
"""
import os
import sys
import tempfile

# Make sure we can import core.report_generator
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'backend'))

from core.report_generator import generate_inspection_pdf  # noqa: E402


def main():
    run_info = {
        'name': '测试巡检任务',
        'started_at': '2026-05-15 23:45:58',
        'total_devices': 2,
        'avg_health_score': 100.0,
        'analysis_summary_json': '{}',
    }
    results = [
        {
            'hostname': 'cisco-sw1',
            'ip_address': '192.168.96.129',
            'platform': 'cisco_ios',
            'site': '北京机房',
            'role': '接入层交换机',
            'health_score': 100,
            'health_status': 'healthy',
            'compliance_status': 'unknown',
            'analysis_json': '[]',
            'findings_json': '[]',
            'metrics_json': '{}',
            'raw_outputs_json': '{}',
            'correlated_risks_json': '[]',
            'checked_at': '2026-05-15 23:45:00',
            'ping_ok': True,
            'ssh_ok': True,
        },
        {
            'hostname': 'cisco-sw2',
            'ip_address': '192.168.96.130',
            'platform': 'cisco_ios',
            'site': '北京机房',
            'role': '汇聚层交换机',
            'health_score': 100,
            'health_status': 'healthy',
            'compliance_status': 'unknown',
            'analysis_json': '[]',
            'findings_json': '[]',
            'metrics_json': '{}',
            'raw_outputs_json': '{}',
            'correlated_risks_json': '[]',
            'checked_at': '2026-05-15 23:45:00',
            'ping_ok': True,
            'ssh_ok': True,
        },
    ]

    out_dir = os.path.join(HERE, '_out')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'test_chinese.pdf')

    generate_inspection_pdf(run_info, results, out_path,
                            customer_name='测试客户', engineer_name='张工程师')
    size = os.path.getsize(out_path)
    print(f'OK: {out_path} ({size} bytes)')

    # Sanity check: PDF should embed the font (look for /Subtype /TrueType
    # and a CIDFont / TrueType font dict referencing simhei).
    with open(out_path, 'rb') as f:
        blob = f.read()
    if b'simhei' in blob.lower() or b'SimHei' in blob:
        print('OK: simhei font reference found in PDF stream')
    else:
        print('WARN: simhei not directly found; checking for any TrueType font...')
        if b'/TrueType' in blob:
            print('OK: TrueType font is embedded')
        else:
            print('FAIL: no embedded TrueType font detected')


if __name__ == '__main__':
    main()
