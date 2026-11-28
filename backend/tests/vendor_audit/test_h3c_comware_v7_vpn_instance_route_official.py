from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402
from services.operational_data_service import resolve_textfsm_template_for_command  # noqa: E402


def test_cr16000_f_vpn_instance_route_preserves_bgp_row_with_spaced_interface():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "h3c"
        / "h3c_comware"
        / "display_ip_routing_table_vpn_instance"
        / "cr16000_f_vpn1_r795x.txt"
    )
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        "display ip routing-table vpn-instance vpn1",
        platform="h3c_comware_v7",
    )

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v7_display_ip_routing_table.textfsm"
    assert result["template_source"] == "custom"
    assert len(result["data"]) == 11
    bgp_routes = [row for row in result["data"] if row["PROTOCOL"] == "BGP"]
    assert bgp_routes == [{
        "DESTINATIONS": "11",
        "ROUTES": "11",
        "DESTINATION": "10.3.1.0/24",
        "PROTOCOL": "BGP",
        "PREFERENCE": "255",
        "COST": "0",
        "NEXTHOP": "3.3.3.9",
        "INTERFACE": "GE 3/1/4",
    }]

    resolver_match = resolve_textfsm_template_for_command(
        {
            "id": "official-cr16000-f-vpn1",
            "platform": "h3c_comware",
            "vendor": "h3c",
            "profile_platform_code": "h3c_comware_v7",
            "profile_parser_platform": "h3c_comware_v7",
            "profile_connection_driver": "hp_comware",
        },
        "display ip routing-table vpn-instance {{vrf}}",
        action_code="get_route_table_vrf",
    )
    assert resolver_match == {
        "textfsm_template": "h3c_comware_v7_display_ip_routing_table.textfsm",
        "textfsm_source": "custom",
        "template_action_code": None,
    }
