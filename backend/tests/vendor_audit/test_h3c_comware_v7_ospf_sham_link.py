from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402


def test_h3c_s6850_ospf_sham_link_neighbor_is_retained_without_interface():
    sample_path = (
        BACKEND_ROOT
        / "tests"
        / "fixtures"
        / "cli"
        / "h3c"
        / "h3c_comware"
        / "display_ospf_peer"
        / "comware_v7_s6850_release_655x.txt"
    )
    result = smart_parse_cli(
        sample_path.read_text(encoding="utf-8"),
        "display ospf peer",
        platform="h3c_comware_v7",
    )

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v7_display_ospf_peer.textfsm"
    assert len(result["data"]) == 2
    assert result["data"][0]["NEIGHBOR_ID"] == "1.1.1.2"
    assert result["data"][0]["INTERFACE"] == "Vlan10"
    assert result["data"][0]["STATUS"] == "Full/DR"
    assert result["data"][1]["NEIGHBOR_ID"] == "22.22.22.22"
    assert result["data"][1]["AREA_ID"] == "0.0.0.0"
    assert result["data"][1]["INTERFACE"] == ""
    assert result["data"][1]["STATUS"] == "Full"
