from __future__ import annotations

from services.operational_data_service import _parse_stp_raw
from services.topology_protocol_service import normalize_protocol_records


def test_protocol_records_normalize_to_non_physical_evidence():
    payload = {
        "collected_at": "2026-08-08T10:00:00+00:00",
        "categories": [
            {"key": "ospf", "success": True, "records": [{
                "neighbor_id": "2.2.2.2", "address": "10.0.0.2", "state": "FULL",
                "interface": "Gi0/0", "area_id": "0.0.0.0",
            }]},
            {"key": "isis", "success": True, "records": [{
                "system_id": "0000.0000.0002", "state": "Up", "interface": "Gi0/1",
            }]},
            {"key": "bgp", "success": True, "records": [{
                "bgp_neigh": "203.0.113.1", "neigh_as": "65001", "local_as": "65000",
                "state_pfxrcd": "Established",
            }]},
            {"key": "routing_table", "success": True, "records": [{
                "prefix": "0.0.0.0/0", "next_hop": "192.0.2.1", "interface": "Gi0/2",
            }]},
            {"key": "interface_description", "success": True, "records": [{
                "interface": "Gi0/3", "remote_device": "CORE-01", "description": "TO-CORE CORE-01",
            }]},
            {"key": "stp", "success": True, "records": [{
                "interface": "Gi0/4", "designated_bridge": "0000.1111.2222", "state": "forwarding",
            }]},
        ],
    }
    rows = normalize_protocol_records({"id": "device-a", "ip_address": "192.0.2.10"}, payload)
    by_protocol = {row["protocol"]: row for row in rows}
    assert by_protocol["ospf"]["relation_type"] == "L3_NEIGHBOR"
    assert by_protocol["ospf"]["semantic_relation"] == "L3_NEIGHBOR"
    assert by_protocol["isis"]["relation_type"] == "L3_NEIGHBOR"
    assert by_protocol["bgp"]["target_identity"] == "203.0.113.1"
    assert by_protocol["bgp"]["semantic_relation"] == "WAN"
    assert by_protocol["routing"]["relation_type"] == "LOGICAL"
    assert by_protocol["interface_description"]["relation_type"] == "HIERARCHICAL"
    assert by_protocol["stp"]["relation_type"] == "L2_NEIGHBOR"
    assert all(row["relation_type"] != "PHYSICAL" for row in rows)


def test_stp_parser_is_conservative_and_keeps_forwarding_state():
    output = """
Interface        Role Sts Cost      Prio.Nbr Type
Gi1/0/1          Desg FWD 4         128.1    P2p
Gi1/0/2          Altn BLK 4         128.2    P2p
Bridge ID        32768.0000.1111.2222
invalid input detected
"""
    records = _parse_stp_raw(output, "cisco_ios")
    assert len(records) == 2
    assert records[0]["interface"] == "Gi1/0/1"
    assert records[0]["state"] == "forwarding"
    assert records[0]["role"] == "designated"
    assert records[1]["state"] == "blocking"
