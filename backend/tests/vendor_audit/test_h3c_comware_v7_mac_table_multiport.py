from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402


def test_h3c_s6850_multiport_mac_entry_preserves_each_egress_port():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "h3c"
        / "h3c_comware"
        / "display_mac_address"
        / "comware_v7_s6850_release_655x.txt"
    )
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        "display mac-address vlan 100",
        platform="h3c_comware_v7",
    )

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v7_display_mac_address.textfsm"
    assert result["data"] == [
        {
            "MAC_ADDRESS": "0001-0101-0101",
            "VLAN_ID": "100",
            "STATUS": "Multiport",
            "INTERFACE": "WGE1/0/1",
            "AGING": "N",
        },
        {
            "MAC_ADDRESS": "0001-0101-0101",
            "VLAN_ID": "100",
            "STATUS": "Multiport",
            "INTERFACE": "WGE1/0/2",
            "AGING": "N",
        },
        {
            "MAC_ADDRESS": "0033-0033-0033",
            "VLAN_ID": "100",
            "STATUS": "Blackhole",
            "INTERFACE": "N/A",
            "AGING": "N",
        },
        {
            "MAC_ADDRESS": "0000-0000-0002",
            "VLAN_ID": "100",
            "STATUS": "Static",
            "INTERFACE": "WGE1/0/3",
            "AGING": "N",
        },
        {
            "MAC_ADDRESS": "00e0-fc00-5829",
            "VLAN_ID": "100",
            "STATUS": "Learned",
            "INTERFACE": "WGE1/0/4",
            "AGING": "Y",
        },
    ]
