import pytest
from services.operational_data_service import _parse_bgp_raw, _parse_ospf_raw, _parse_bgp_routes_raw
from services.ip_locator_service import _collect_device_vrfs, get_bgp_routes
from services.diagnose_service import match_route_offline, get_device_vrf_for_ip, trace_route_path_async
from database.schema import get_db_connection

def test_bgp_raw_parser_fallback():
    # Test Cisco style BGP summary output
    cisco_output = """
    BGP router identifier 10.0.0.1, local AS number 65001
    BGP table version is 10, main routing table version 10
    5 BGP path attributes and 5 BGP route map entries used

    Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
    10.0.0.2        4        65002     105     106        7    0    0 01:23:45 12
    10.0.0.3        4        65003       0       0        0    0    0 never    Active
    """
    records = _parse_bgp_raw(cisco_output, 'cisco_ios')
    assert len(records) == 2
    assert records[0]['bgp_neigh'] == '10.0.0.2'
    assert records[0]['neigh_as'] == '65002'
    assert records[0]['state_pfxrcd'] == '12'
    assert records[0]['up_down'] == '01:23:45'
    assert records[0]['local_as'] == 65001
    
    assert records[1]['bgp_neigh'] == '10.0.0.3'
    assert records[1]['neigh_as'] == '65003'
    assert records[1]['state_pfxrcd'] == 'Active'
    assert records[1]['up_down'] == 'never'
    assert records[1]['local_as'] == 65001

    # Test Huawei style BGP peer output
    huawei_output = """
     BGP local router ID : 10.0.0.1
     Local AS number : 65001
     Total number of peers : 1                  Peers in established state : 1

     Peer            V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State PrefRcv
     10.0.0.2        4       65002      105      106     0  01:24:00 Established      12
    """
    records_hw = _parse_bgp_raw(huawei_output, 'huawei_vrp')
    assert len(records_hw) == 1
    assert records_hw[0]['bgp_neigh'] == '10.0.0.2'
    assert records_hw[0]['neigh_as'] == '65002'
    assert records_hw[0]['state_pfxrcd'] == '12'
    assert records_hw[0]['up_down'] == '01:24:00'
    assert records_hw[0]['local_as'] == 65001


def test_ospf_raw_parser_fallback():
    # Test Cisco style OSPF neighbor output
    cisco_output = """
    Neighbor ID     Pri   State           Dead Time   Address         Interface
    2.2.2.2           1   FULL/DR         00:00:36    10.0.0.2        GigabitEthernet0/1
    """
    records = _parse_ospf_raw(cisco_output, 'cisco_ios')
    assert len(records) == 1
    assert records[0]['neighbor_id'] == '2.2.2.2'
    assert records[0]['state'] == 'FULL/DR'
    assert records[0]['address'] == '10.0.0.2'
    assert records[0]['interface'] == 'GigabitEthernet0/1'

    # Test Huawei style OSPF peer output
    huawei_output = """
         OSPF Process 1 with Router ID 10.0.0.1
             Neighbors

       Area 0.0.0.0 interface 10.0.0.1(GigabitEthernet0/1)'s neighbors
       Router ID: 2.2.2.2          Address: 10.0.0.2        GR State: Normal
       State: Full  Mode: Nbr is  Master  Priority: 1
    """
    records_hw = _parse_ospf_raw(huawei_output, 'huawei_vrp')
    assert len(records_hw) == 1
    assert records_hw[0]['neighbor_id'] == '2.2.2.2'
    assert records_hw[0]['address'] == '10.0.0.2'
    assert records_hw[0]['state'] == 'Full'
    assert records_hw[0]['interface'] == 'Gigaintf:GigabitEthernet0/1' or records_hw[0]['interface'] == 'GigabitEthernet0/1'


def test_vrf_discovery_parser():
    cisco_vrf_out = """
    Name                             Default RD          Protocols   Interfaces
    vrf-a                            1:1                 ipv4        Gi0/1
    vrf-b                            2:2                 ipv4        Gi0/2
    """
    class MockDev:
        def get(self, key, default=None):
            return 'cisco_ios'
            
    # Test mock VRF parsing helper using raw output matching
    mock_dev = {'platform': 'cisco_ios', 'hostname': 'R1'}
    # We can inject mock output by hooking _send_command
    import services.ip_locator_service
    orig_send = services.ip_locator_service._send_command
    try:
        services.ip_locator_service._send_command = lambda dev, cmd: cisco_vrf_out
        vrfs = _collect_device_vrfs(mock_dev)
        assert 'vrf-a' in vrfs
        assert 'vrf-b' in vrfs
        assert 'default' in vrfs
    finally:
         services.ip_locator_service._send_command = orig_send


def test_vrf_route_matching_and_diagnose(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM route_table")
        conn.execute("DELETE FROM vrfs")
        conn.execute("DELETE FROM ip_addresses")
        conn.execute("DELETE FROM topology_links")

        # 1. Insert devices
        conn.execute("INSERT INTO devices (id, hostname, ip_address, platform, status, role) VALUES ('dev-r1', 'R1', '10.0.0.1', 'cisco_ios', 'online', 'router')")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, platform, status, role) VALUES ('dev-r2', 'R2', '10.0.0.2', 'cisco_ios', 'online', 'router')")

        # 2. Insert VRFs
        conn.execute("INSERT INTO vrfs (id, vrf_name, rd) VALUES ('vrf-a-id', 'vrf-a', '1:1')")

        # 3. Insert IP addresses linking R2 to vrf-a
        conn.execute("INSERT INTO ip_addresses (id, subnet_id, address, device_id, vrf_id, created_at, updated_at) VALUES ('ip-1', 'sub-1', '10.0.0.2', 'dev-r2', 'vrf-a-id', '2026-06-14', '2026-06-14')")

        # 4. Insert dynamic routes in route_table
        # R1 has:
        # - destination 10.0.0.2/32 in vrf-a via 10.0.0.2 (GigabitEthernet0/1)
        # - destination 8.8.8.8/32 in default via 10.0.0.2 (GigabitEthernet0/1) [leaked]
        conn.execute(
            "INSERT INTO route_table (id, device_id, vrf_name, destination, next_hop, outgoing_interface, protocol,metric, preference, last_updated, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, '2026-06-14', 1)",
            ('r-entry-1', 'dev-r1', 'vrf-a', '10.0.0.2/32', '10.0.0.2', 'GigabitEthernet0/1', 'static')
        )
        conn.execute(
            "INSERT INTO route_table (id, device_id, vrf_name, destination, next_hop, outgoing_interface, protocol,metric, preference, last_updated, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, '2026-06-14', 1)",
            ('r-entry-2', 'dev-r1', 'default', '8.8.8.8/32', '10.0.0.2', 'GigabitEthernet0/1', 'static')
        )
        
        # 5. Topology link connecting R1 to R2
        conn.execute(
            "INSERT INTO topology_links (id, source_device_id, source_hostname, source_port, source_port_normalized, target_device_id, target_hostname, target_port, target_port_normalized, status, last_seen) "
            "VALUES ('link-1', 'dev-r1', 'R1', 'GigabitEthernet0/1', 'gi0/1', 'dev-r2', 'R2', 'GigabitEthernet0/1', 'gi0/1', 'active', '2026-06-14')"
        )
        conn.commit()

        # Test LPM matching in vrf-a
        routes = match_route_offline('dev-r1', '10.0.0.2', 'vrf-a')
        assert len(routes) == 1
        assert routes[0]['vrf_name'] == 'vrf-a'

        # Test LPM leak fallback matching (from vrf-a fallback to default)
        routes_leak = match_route_offline('dev-r1', '8.8.8.8', 'vrf-a')
        assert len(routes_leak) == 1
        assert routes_leak[0]['vrf_name'] == 'default'

        # Test VRF lookup helper
        assert get_device_vrf_for_ip(conn, 'dev-r2', '10.0.0.2') == 'vrf-a'

    finally:
        conn.close()


def test_parse_bgp_routes_raw():
    # Cisco style raw BGP route table (including prefix-omission / alternative path)
    cisco_output = """
BGP table version is 10, local router ID is 1.1.1.1
Status codes: s suppressed, d damped, h history, * valid, > best, i - internal,
              r RIB-failure, S Stale, m multipath, b backup-path, f RT-Filter,
              x best-external, a additional-path, c RIB-compressed,
Origin codes: i - IGP, e - EGP, ? - incomplete

   Network          Next Hop            Metric LocPrf Weight Path
*> 10.1.0.0/16      192.168.1.1              0    100      0 65001 i
*                   192.168.1.3              0    100      0 65003 i
*> 2001:db8::/32    2001:db8::1              0    100      0 65003 i
    """
    records = _parse_bgp_routes_raw(cisco_output, 'cisco_ios')
    assert len(records) == 3
    
    assert records[0]['prefix'] == '10.1.0.0/16'
    assert records[0]['next_hop'] == '192.168.1.1'
    assert records[0]['is_best'] == 1
    assert records[0]['as_path'] == '65001 i'
    
    assert records[1]['prefix'] == '10.1.0.0/16'
    assert records[1]['next_hop'] == '192.168.1.3'
    assert records[1]['is_best'] == 0
    assert records[1]['as_path'] == '65003 i'
    
    assert records[2]['prefix'] == '2001:db8::/32'
    assert records[2]['next_hop'] == '2001:db8::1'
    assert records[2]['is_best'] == 1
    assert records[2]['as_path'] == '65003 i'


def test_get_bgp_routes_database(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM bgp_route_table")
        conn.execute("DELETE FROM devices")
        
        # Insert mock device
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, platform, status, role) "
            "VALUES ('dev-r1', 'R1', '10.0.0.1', 'cisco_ios', 'online', 'router')"
        )
        
        # Insert mock BGP routes
        conn.execute(
            "INSERT INTO bgp_route_table (id, device_id, vrf_name, prefix, next_hop, metric, loc_pref, weight, as_path, is_best, is_active, last_updated) "
            "VALUES ('bgp-1', 'dev-r1', 'default', '10.1.0.0/16', '192.168.1.1', 0, 100, 0, '65001 i', 1, 1, '2026-06-14')"
        )
        conn.execute(
            "INSERT INTO bgp_route_table (id, device_id, vrf_name, prefix, next_hop, metric, loc_pref, weight, as_path, is_best, is_active, last_updated) "
            "VALUES ('bgp-2', 'dev-r1', 'default', '10.1.0.0/16', '192.168.1.3', 0, 100, 0, '65003 i', 0, 0, '2026-06-14')"
        )
        conn.commit()
        
        # Query BGP routes
        res = get_bgp_routes()
        assert res['total'] == 2
        assert len(res['entries']) == 2
        assert res['entries'][0]['prefix'] == '10.1.0.0/16'
        assert res['entries'][0]['device_name'] == 'R1'
        assert res['entries'][0]['is_best'] == 1
        assert res['entries'][1]['is_best'] == 0
        
    finally:
        conn.close()


def test_parse_interface_counters_multi_vendor():
    from services.diagnose_service import parse_interface_counters
    
    # Test Cisco
    cisco_out = """
    GigabitEthernet0/1 is up, line protocol is up
      Input queue: 0/75/0/0 (size/max/drops/flushes); Total output drops: 15
      23 input errors, 12 CRC, 0 frame, 0 overrun, 0 ignored
      0 output errors, 0 collisions, 0 interface resets
    """
    res_cisco = parse_interface_counters(cisco_out, 'cisco_ios')
    assert res_cisco['input_errors'] == 23
    assert res_cisco['crc'] == 12
    assert res_cisco['output_drops'] == 15

    # Test Huawei/H3C
    huawei_out = """
    GigabitEthernet0/1 current state: UP
    Last 300 seconds input utility rate: 0.01%
    Input: 45 errors, 0 discarded, 0 frame errors, 8 CRC
    Output: 0 errors, 19 discarded, 0 buffer failures
    """
    res_hw = parse_interface_counters(huawei_out, 'huawei_vrp')
    assert res_hw['input_errors'] == 45
    assert res_hw['crc'] == 8
    assert res_hw['output_drops'] == 19

    # Test Juniper
    juniper_out = """
    Physical interface: ge-0/0/0, Enabled, Physical link is Up
      Input packets: 12345, Output packets: 54321
      Input errors:
        Errors: 7, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0, L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0, FIFO errors: 0, Resource errors: 0
      Output errors:
        Carrier transitions: 0, Errors: 0, Drops: 31, Collisions: 0, Aged packets: 0, FIFO errors: 0, HS link FO errors: 0, MTU errors: 0, Resource errors: 0
    """
    res_juni = parse_interface_counters(juniper_out, 'juniper_junos')
    assert res_juni['input_errors'] == 7
    assert res_juni['output_drops'] == 31


