from pathlib import Path

from core.textfsm import smart_parse_cli
from services.ip_locator_service import parse_routing_table
from services.operational_data_service import _parse_command_output, _resolve_commands


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli"


VRP5_ROUTING_TABLE = """<LSW2>dis ip routing-table
Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface
        0.0.0.0/0   Static  60   0          RD   10.253.1.1      Vlanif12
        8.8.8.8/32  EBGP    255  0           D   10.253.1.1      Vlanif12
     10.253.0.5/32  OSPF    10   2           D   10.253.1.14     Vlanif24
                    OSPF    10   2           D   10.253.1.10     Vlanif23
"""


def test_vrp5_routing_table_parses_ebgp_and_ecmp_continuations():
    records = parse_routing_table(VRP5_ROUTING_TABLE, "huawei_vrp")

    assert len(records) == 4
    assert records[1]["protocol"] == "bgp"
    assert records[1]["preference"] == 255
    assert records[2]["prefix"] == records[3]["prefix"] == "10.253.0.5"
    assert {row["next_hop"] for row in records[2:]} == {"10.253.1.10", "10.253.1.14"}


def test_vrp5_operational_catalog_and_routing_category_return_records():
    assert _resolve_commands("huawei_vrp", ["routing_table", "bgp", "bgp_routes"]) == {
        "routing_table": ["display ip routing-table"],
        "bgp": ["display bgp peer"],
        "bgp_routes": ["display bgp routing-table"],
    }
    records = _parse_command_output(
        "huawei_vrp", "routing_table", "display ip routing-table", VRP5_ROUTING_TABLE
    )
    assert len(records) == 4


def test_huawei_bgp_peer_exposes_local_and_remote_as():
    output = (FIXTURES / "huawei" / "huawei_vrpv8" / "display_bgp_peer" / "vrpv8_ce16800.txt").read_text()
    result = smart_parse_cli(output, "display bgp peer", platform="huawei_vrp")

    assert result["success"] is True
    assert {row["PEER"] for row in result["data"]} == {"10.9.0.8", "10.10.0.10"}
    assert {row["LOCAL_AS_NUMBER"] for row in result["data"]} == {"65001"}
    assert {row["REMOTE_AS"] for row in result["data"]} == {"100", "200"}


def test_h3c_bgp_route_columns_are_not_left_in_attributes():
    output = (FIXTURES / "h3c" / "h3c_comware" / "display_bgp_routing_table_ipv4" / "comware_v7_router_b.txt").read_text()
    records = _parse_command_output(
        "h3c_comware", "bgp_routes", "display bgp routing-table ipv4", output
    )

    assert records == [{
        "prefix": "8.1.1.0/24",
        "next_hop": "3.1.1.2",
        "metric": 0,
        "loc_pref": 0,
        "weight": 0,
        "as_path": "65008i",
        "is_best": 1,
        "is_active": 1,
        "status": "* >e",
    }]
