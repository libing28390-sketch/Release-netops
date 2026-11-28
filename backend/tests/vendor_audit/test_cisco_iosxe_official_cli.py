from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import list_templates, smart_parse_cli  # noqa: E402
from services.operational_data_service import resolve_textfsm_template_for_command  # noqa: E402


def test_catalyst_9300_ios_xe_mac_table_sample_matches_action_template():
    output = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "cisco"
        / "cisco_iosxe"
        / "show_mac_address_table"
        / "catalyst9300_iosxe_17_18.txt"
    ).read_text(encoding="utf-8")

    result = smart_parse_cli(output, "show mac address-table", platform="cisco_xe")

    assert result["success"] is True
    assert result["template"] == "cisco_ios_show_mac_address_table.textfsm"
    assert [(row["VLAN"], row["MAC_ADDRESS"], row["TYPE"], row["INTERFACE"]) for row in result["data"]] == [
        ("All", "0100.0ccc.cccc", "STATIC", "CPU"),
        ("1", "780c.f0e1.1dc3", "STATIC", "Vl1"),
        ("1021", "0002.02cc.0002", "STATIC", "Gi6/0/2"),
    ]


def test_cisco_mac_table_template_matches_the_release_command_in_the_catalog():
    device = {
        "platform": "cisco_ios",
        "vendor": "Cisco",
        "profile_platform_code": "cisco_ios",
        "profile_parser_platform": "cisco_ios",
    }
    match = resolve_textfsm_template_for_command(
        device,
        "show mac address-table",
        action_code="get_mac_table",
        templates_catalog=list_templates(vendor_filter="cisco"),
    )

    assert match is not None
    assert match["textfsm_template"] == "cisco_ios_show_mac_address_table.textfsm"


def test_cisco_ios_isis_sample_preserves_levels_in_quick_ops():
    from services.platform_registry_service import _normalize_records

    output = (
        BACKEND_ROOT / "tests/fixtures/cli/cisco/cisco_ios/show_isis_neighbors/ios_12_0_29_s.txt"
    ).read_text(encoding="utf-8")
    parsed = smart_parse_cli(output, "show isis neighbors", platform="cisco_ios")
    assert parsed["success"] is True
    records = _normalize_records(
        parsed["data"],
        max_records=1000,
        expected_fields={"neighbor", "state", "interface", "system_id", "level"},
    )
    assert [
        (record["neighbor"], record["interface"], record["level"]) for record in records
    ] == [
        ("0000.0000.0002", "Et0/0", "L1"),
        ("0000.0000.0002", "Et0/0", "L2"),
    ]
    assert _normalize_records(
        [{"TYPE": "L1"}], max_records=1000, expected_fields={"type"}
    ) == [{"type": "L1"}]
