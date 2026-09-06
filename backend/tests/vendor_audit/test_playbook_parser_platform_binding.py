import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import _template_platform_candidates


def test_parser_platform_families_allow_only_safe_compatibility_fallbacks():
    assert set(_template_platform_candidates('huawei_vrp')).intersection(
        _template_platform_candidates('huawei_vrpv8')
    )
    # Versionless templates are the explicit common grammar and may be used
    # only after the concrete H3C version has been tried.
    assert _template_platform_candidates('h3c_comware') == ['h3c_comware_v7', 'h3c_comware']
    assert _template_platform_candidates('h3c_comware_v3') == [
        'h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware',
    ]
    assert _template_platform_candidates('h3c_comware_v5') == ['h3c_comware_v5', 'h3c_comware']
    assert _template_platform_candidates('h3c_comware_v9') == ['h3c_comware_v9', 'h3c_comware']
    assert not set(_template_platform_candidates('huawei_vrp')).intersection(
        _template_platform_candidates('cisco_ios')
    )
