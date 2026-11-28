from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import list_templates, smart_parse_cli  # noqa: E402
from services.operational_data_service import resolve_textfsm_template_for_command  # noqa: E402


def test_h3c_s6850_vlan_brief_combines_all_port_continuation_lines():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "h3c"
        / "h3c_comware"
        / "display_vlan_brief"
        / "comware_v7_s6850_release_655x.txt"
    )
    command = "display vlan brief"
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        command,
        platform="h3c_comware_v7",
    )

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v7_display_vlan_brief.textfsm"
    assert len(result["data"]) == 3
    assert result["data"][0] == {
        "VLAN_ID": "1",
        "VLAN_NAME": "VLAN 0001",
        "PORTS": "WGE1/0/1 WGE1/0/2 WGE1/0/3 WGE1/0/4 WGE1/0/5 WGE1/0/6 WGE1/0/7 WGE1/0/8 WGE1/0/9",
    }
    assert result["data"][1] == {"VLAN_ID": "2", "VLAN_NAME": "VLAN 0002", "PORTS": ""}

    match = resolve_textfsm_template_for_command(
        {
            "platform": "h3c_comware",
            "vendor": "H3C",
            "profile_platform_code": "h3c_comware",
            "profile_parser_platform": "h3c_comware",
            "profile_connection_driver": "hp_comware",
        },
        command,
        action_code="get_vlan_table",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )
    assert match is not None
    assert match["textfsm_template"] == "h3c_comware_v7_display_vlan_brief.textfsm"
