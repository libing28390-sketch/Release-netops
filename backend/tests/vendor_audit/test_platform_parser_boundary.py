import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.operational_data_service import _resolve_ntc_platform


def test_secondary_parser_never_defaults_recognized_non_cisco_platform_to_cisco():
    assert _resolve_ntc_platform('dptech_conplat') == 'dptech_ios'
    assert _resolve_ntc_platform('dptech_conplat_fw') == 'dptech_ios'
    assert _resolve_ntc_platform('ruijie_rgos') == 'ruijie_rgos'
    assert _resolve_ntc_platform('h3c_comware_v9') == 'h3c_comware'


def test_unknown_platform_is_kept_for_an_unmatched_parse():
    assert _resolve_ntc_platform('vendor_private_os') == 'vendor_private_os'
