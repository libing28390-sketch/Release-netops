from core.textfsm import smart_parse_cli
from services.operational_data_service import _resolve_commands


RAW_HUAWEI_LLDP_BRIEF = """<acc-huawei-sw1>DIS lldp neighbor brief
Local Interface         Exptime(s) Neighbor Interface      Neighbor Device
-------------------------------------------------------------------------------
GE1/0/1                       105  GigabitEthernet3/0      acc-h3c-sw2
<acc-huawei-sw1>"""


def test_huawei_lldp_brief_catalog_uses_display_brief():
    assert _resolve_commands("huawei_vrpv8", ["neighbors"]) == {
        "neighbors": ["display lldp neighbor brief"]
    }


def test_huawei_lldp_brief_output_is_parsed():
    for platform in ("huawei_vrp", "huawei_vrpv8"):
        result = smart_parse_cli(
            RAW_HUAWEI_LLDP_BRIEF,
            "display lldp neighbor brief",
            platform=platform,
        )
        assert result["success"] is True
        assert result["matched_rows"] == 1
        assert result["data"] == [
            {
                "INTERFACE": "GE1/0/1",
                "NEIGHBOR_NAME": "acc-h3c-sw2",
                "NEIGHBOR_INTERFACE": "GigabitEthernet3/0",
                "EXPIRED_TIME": "105",
            }
        ]
