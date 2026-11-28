from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402


def test_catalyst_9300_show_vlan_brief_official_sample_uses_ntc_builtin():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "cisco"
        / "cisco_iosxe"
        / "show_vlan_brief"
        / "catalyst9300_unknown_iosxe.txt"
    )
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        "show vlan brief",
        platform="cisco_xe",
    )

    assert result["success"] is True
    assert result["template"] == "cisco_ios_show_vlan.textfsm"
    assert result["template_source"] == "builtin"
    assert len(result["data"]) == 1
    assert result["data"][0]["VLAN_ID"] == "1"
    assert result["data"][0]["VLAN_NAME"] == "default"
    assert result["data"][0]["STATUS"] == "active"
    assert result["data"][0]["INTERFACES"] == [
        "Gi1/0/2",
        "Gi1/0/3",
        "Gi1/0/4",
        "Gi1/0/5",
        "Gi1/0/6",
        "Gi1/0/7",
        "Gi1/0/8",
        "Gi1/0/9",
        "Gi1/0/10",
        "Gi1/0/11",
        "Gi1/0/13",
    ]
