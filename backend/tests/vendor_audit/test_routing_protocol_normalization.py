from services.ip_locator_service import parse_routing_table
from services.operational_data_service import (
    _normalize_records,
    _parse_dynamic_neighbor_raw,
)


def test_textfsm_record_keys_are_normalized_once_at_operational_boundary():
    records = _normalize_records([{
        "NEIGHBOR_ID": "2.2.2.2",
        "IP-ADDRESS": "10.1.12.2",
        "STATUS": "FULL/DR",
    }])

    assert records == [{
        "neighbor_id": "2.2.2.2",
        "ip_address": "10.1.12.2",
        "status": "FULL/DR",
    }]


def test_cisco_route_codes_are_canonicalized_for_dynamic_protocol_detection():
    output = """
      10.0.0.0/8 is variably subnetted, 6 subnets, 2 masks
C        10.1.12.0/24 is directly connected, Ethernet0/3
L        10.1.12.1/32 is directly connected, Ethernet0/3
S        10.2.0.0/16 [1/0] via 10.1.12.2
O        10.3.0.0/16 [110/20] via 10.1.12.2, Ethernet0/3
D        10.4.0.0/16 [90/20] via 10.1.12.2, Ethernet0/3
i        10.5.0.0/16 [115/20] via 10.1.12.2, Ethernet0/3
"""

    protocols = [row["protocol"] for row in parse_routing_table(output, "cisco_ios")]

    assert protocols == ["connected", "local", "static", "ospf", "eigrp", "isis"]


def test_juniper_route_protocol_is_not_forced_to_static():
    output = """
10.0.0.0/24 *[OSPF/10] 00:00:05
                    > to 10.0.0.1 via ge-0/0/0.0
10.0.1.0/24 *[Direct/0] 00:00:05
                    > via ge-0/0/1.0
"""

    routes = parse_routing_table(output, "juniper_junos")

    assert [row["protocol"] for row in routes] == ["ospf", "connected"]


def test_dynamic_neighbor_fallback_parsers_return_common_fields():
    eigrp = """
    H   Address                 Interface       Hold Uptime   SRTT   RTO  Q  Seq
    0   10.1.12.2               Et0/3           12  00:10:00  5    300  0  4
    """
    rip = """
    10.2.0.0/16 via 10.1.12.2, Ethernet0/3, 00:00:12
    """

    eigrp_rows = _parse_dynamic_neighbor_raw(eigrp, "eigrp")
    rip_rows = _parse_dynamic_neighbor_raw(rip, "rip")

    assert eigrp_rows[0]["address"] == "10.1.12.2"
    assert eigrp_rows[0]["interface"] == "Et0/3"
    assert rip_rows[0]["address"] == "10.1.12.2"
    assert rip_rows[0]["interface"] == "Ethernet0/3"
