from pathlib import Path

from core.textfsm import smart_parse_cli
from services.ip_locator_service import parse_routing_table
from services.operational_data_service import _parse_command_output, _resolve_commands
from services.scheduler_service import _bgp_route_identity


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli"


VRP5_ROUTING_TABLE = """<LSW2>dis ip routing-table
Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface
        0.0.0.0/0   Static  60   0          RD   10.253.1.1      Vlanif12
        8.8.8.8/32  EBGP    255  0           D   10.253.1.1      Vlanif12
     10.253.0.5/32  OSPF    10   2           D   10.253.1.14     Vlanif24
                    OSPF    10   2           D   10.253.1.10     Vlanif23
"""


COMWARE_ROUTING_TABLE_WITHOUT_FLAGS = """<S6850-4>display ip routing-table
Destinations : 37    Routes : 41
Destination/Mask   Proto   Pre Cost        NextHop         Interface
0.0.0.0/0          O_ASE2  150 1           10.254.14.1    FGE1/0/54
10.254.0.0/24      Direct  0   0           10.254.0.4    Vlan100
"""


def test_vrp5_routing_table_parses_ebgp_and_ecmp_continuations():
    records = parse_routing_table(VRP5_ROUTING_TABLE, "huawei_vrp")

    assert len(records) == 4
    assert records[1]["protocol"] == "bgp"
    assert records[1]["preference"] == 255
    assert records[2]["prefix"] == records[3]["prefix"] == "10.253.0.5"
    assert {row["next_hop"] for row in records[2:]} == {"10.253.1.10", "10.253.1.14"}


def test_comware_routing_table_without_flags_column_parses_routes():
    records = parse_routing_table(COMWARE_ROUTING_TABLE_WITHOUT_FLAGS, "hp_comware")

    assert len(records) == 2
    assert records[0]["prefix"] == "0.0.0.0"
    assert records[0]["preference"] == 150
    assert records[0]["metric"] == 1
    assert records[0]["next_hop"] == "10.254.14.1"
    assert records[0]["interface"] == "FGE1/0/54"


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


def test_bgp_route_identity_keeps_best_and_backup_paths_distinct():
    base = {
        "device_id": "device-1",
        "vrf_name": "default",
        "prefix": "172.16.5.0/24",
        "next_hop": "10.254.0.5",
        "metric": 0,
        "loc_pref": 100,
        "weight": 0,
        "as_path": "i",
        "local_as": 65000,
        "is_best": 1,
        "is_active": 1,
    }
    backup = {**base, "is_best": 0, "is_active": 0}
    assert _bgp_route_identity(base) != _bgp_route_identity(backup)
    assert _bgp_route_identity(base) == _bgp_route_identity({**base})
