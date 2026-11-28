from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402


def test_catalyst_9300_ios_xe_show_vlan_official_sample_uses_ntc_builtin():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "cisco"
        / "cisco_iosxe"
        / "show_vlan"
        / "catalyst9300_iosxe_17_18.txt"
    )
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        "show vlan",
        platform="cisco_xe",
    )

    assert result["success"] is True
    assert result["template"] == "cisco_ios_show_vlan.textfsm"
    assert result["template_source"] == "builtin"
    assert len(result["data"]) == 8
    assert result["data"][0]["VLAN_ID"] == "1"
    assert result["data"][0]["VLAN_NAME"] == "default"
    assert len(result["data"][0]["INTERFACES"]) == 47
    assert result["data"][0]["INTERFACES"][-1] == "Gi1/0/48"
    assert result["data"][-1]["VLAN_ID"] == "1005"
    assert result["data"][-1]["STATUS"] == "act/unsup"
